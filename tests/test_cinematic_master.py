from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from PIL import Image

A = "0" * 32
SCENE = "2" * 32


def _project(monkeypatch, tmp_path: Path, shots: int = 3):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    storage = importlib.import_module("app.video.storage")
    Image.new("RGB", (24, 16), (10, 20, 30)).save(storage.video_asset_path(A, "png"))
    created = service.create_project(
        models.ProjectCreateRequest(
            title="Master",
            master_prompt="SCENE 1: Main\nContinuous action.",
            target_duration_seconds=max(10, shots * 5),
            delivery_fps=120,
            delivery_resolution="2160p",
            aspect_ratio="16:9",
            reference_image_ids=[A],
        )
    )
    scene_shots = [
        models.CinematicShot(
            shot_id=f"{index + 10:032x}",
            ordinal=index + 1,
            title=f"Shot {index + 1}",
            prompt=f"Motion {index + 1}",
            duration_seconds=5,
        )
        for index in range(shots)
    ]
    scene = models.CinematicScene(
        scene_id=SCENE,
        ordinal=1,
        title="Main",
        source_text="Continuous action.",
        target_duration_seconds=shots * 5,
        shots=scene_shots,
    )
    return models, service, storage, service.update_project(
        created.id, models.ProjectUpdateRequest(expected_revision=1, scenes=[scene])
    )


def test_render_all_missing_schedules_every_unrendered_shot_in_order(monkeypatch, tmp_path):
    _, service, storage, project = _project(monkeypatch, tmp_path, shots=3)
    engine = importlib.import_module("app.video.engine")
    jobs = importlib.import_module("app.video.jobs")
    requests = importlib.import_module("app.video.cinematic_requests")
    engine._ENGINE_REGISTRY.clear()
    engine.register_engine(engine.FakeVideoEngine())

    submitted = []
    class CapturePool:
        def submit(self, fn, *args, **kwargs):
            submitted.append((fn, args, kwargs))
            return object()
    monkeypatch.setattr(jobs, "pool", CapturePool())

    result = service.render_project_missing(
        project.id,
        requests.BatchRenderRequest(expected_revision=2, engine_name="fake", max_shots=10),
    )
    assert len(result["jobs"]) == 3
    assert [item["shot_id"] for item in result["jobs"]] == [shot.shot_id for shot in project.scenes[0].shots]
    assert result["project"]["revision"] == 5
    assert len(submitted) == 3
    refreshed = service.get_project(project.id)
    assert all(shot.latest_job_id for shot in refreshed.scenes[0].shots)
    assert all(storage.get_video_record("video_job", shot.latest_job_id)["project_id"] == project.id for shot in refreshed.scenes[0].shots)

    again = service.render_project_missing(
        project.id,
        requests.BatchRenderRequest(expected_revision=5, engine_name="fake", max_shots=10),
    )
    assert again["jobs"] == []
    assert again["skipped"] == 3


def test_project_render_status_distinguishes_missing_active_failed_and_succeeded(monkeypatch, tmp_path):
    _, service, storage, project = _project(monkeypatch, tmp_path, shots=4)
    shots = project.scenes[0].shots
    jobs = []
    for index, status in enumerate(("succeeded", "queued", "failed")):
        record = storage.put_video_record(
            "video_job",
            {
                "status": status,
                "stage": status.title(),
                "progress": 100 if status == "succeeded" else 0,
                "image_id": A,
                "prompt_chars": 10,
                "project_id": project.id,
                "scene_id": SCENE,
                "shot_id": shots[index].shot_id,
                "project_revision": 2,
                **({"asset_id": f"{100 + index:032x}", "asset_url": f"/api/video/assets/{100 + index:032x}.mp4"} if status == "succeeded" else {}),
            },
        )
        jobs.append(record)
    updated_shots = []
    for index, shot in enumerate(shots):
        updated_shots.append(shot.model_copy(update={"latest_job_id": jobs[index]["id"]}) if index < 3 else shot)
    scene = project.scenes[0].model_copy(update={"shots": updated_shots})
    project = service.update_project(project.id, importlib.import_module("app.video.cinematic_models").ProjectUpdateRequest(expected_revision=2, scenes=[scene]))

    status = service.project_render_status(project.id)
    assert status["total_shots"] == 4
    assert status["succeeded"] == 1
    assert status["active"] == 1
    assert status["failed"] == 1
    assert status["missing"] == 1
    assert status["ready_for_assembly"] is False


def test_master_assembly_requires_every_shot_successful(monkeypatch, tmp_path):
    _, service, _, project = _project(monkeypatch, tmp_path, shots=2)
    requests = importlib.import_module("app.video.cinematic_requests")
    with pytest.raises(service.MasterAssemblyNotReady, match="2 shot"):
        service.assemble_project_master(
            project.id,
            requests.AssembleMasterRequest(expected_revision=2, ffmpeg_path="ffmpeg"),
        )


def test_master_assembly_persists_ordered_master_record_without_mutating_project(monkeypatch, tmp_path):
    _, service, storage, project = _project(monkeypatch, tmp_path, shots=2)
    requests = importlib.import_module("app.video.cinematic_requests")
    shots = project.scenes[0].shots
    linked = []
    for index, shot in enumerate(shots):
        asset_id = f"{200 + index:032x}"
        source = storage.video_asset_path(asset_id, "mp4")
        source.write_bytes(b"\x00\x00\x00\x18ftypmp42source")
        job = storage.put_video_record(
            "video_job",
            {
                "status": "succeeded",
                "stage": "Ready",
                "progress": 100,
                "image_id": A,
                "prompt_chars": 8,
                "fps": 24,
                "resolution": "1080p",
                "duration_seconds": 5,
                "project_id": project.id,
                "scene_id": SCENE,
                "shot_id": shot.shot_id,
                "project_revision": 2,
                "asset_id": asset_id,
                "asset_url": f"/api/video/assets/{asset_id}.mp4",
            },
        )
        linked.append(shot.model_copy(update={"latest_job_id": job["id"]}))
    project = service.update_project(
        project.id,
        importlib.import_module("app.video.cinematic_models").ProjectUpdateRequest(
            expected_revision=2,
            scenes=[project.scenes[0].model_copy(update={"shots": linked})],
        ),
    )

    seen = {}
    def fake_run(command, **kwargs):
        seen["command"] = command
        output = Path(command[-1])
        output.write_bytes(b"\x00\x00\x00\x18ftypmp42master")
        class Result:
            returncode = 0
            stdout = ""
            stderr = ""
        return Result()

    monkeypatch.setattr(service, "_run_master_ffmpeg", fake_run)
    before_revision = project.revision
    result = service.assemble_project_master(
        project.id,
        requests.AssembleMasterRequest(expected_revision=before_revision, ffmpeg_path="ffmpeg"),
    )
    assert result["status"] == "ready"
    assert result["project_id"] == project.id
    assert result["project_revision"] == before_revision
    assert result["source_shot_count"] == 2
    assert result["asset_url"].endswith(".mp4")
    assert storage.video_asset_path(result["asset_id"], "mp4").is_file()
    assert service.get_project(project.id).revision == before_revision
    assert seen["command"][0] == "ffmpeg"
    graph = seen["command"][seen["command"].index("-filter_complex") + 1]
    assert "concat=n=2:v=1:a=0[v]" in graph
    assert "scale=3840:2160" in graph
    assert graph.count("tpad=stop_mode=clone:stop_duration=5.0") == 2
    assert graph.count("trim=duration=5.0") == 2
    assert result["timeline_seconds"] == 10
    assert result["actual_video_probe_verified"] is False
    masters = [item for item in storage.list_video_records("video_master") if item["project_id"] == project.id]
    assert masters and masters[0]["asset_id"] == result["asset_id"]


def test_render_status_does_not_claim_assembly_ready_when_successful_job_media_is_missing(monkeypatch, tmp_path):
    _, service, storage, project = _project(monkeypatch, tmp_path, shots=1)
    shot = project.scenes[0].shots[0]
    absent_asset = "f" * 32
    job = storage.put_video_record(
        "video_job", {
            "status": "succeeded",
            "project_id": project.id,
            "scene_id": SCENE,
            "shot_id": shot.shot_id,
            "asset_id": absent_asset,
        },
    )
    scene = project.scenes[0].model_copy(update={
        "shots": [shot.model_copy(update={"latest_job_id": job["id"]})],
    })
    service.update_project(
        project.id,
        importlib.import_module("app.video.cinematic_models").ProjectUpdateRequest(
            expected_revision=2, scenes=[scene],
        ),
    )
    result = service.project_render_status(project.id)
    assert result["total_shots"] == 1
    assert result["succeeded"] == 1
    assert result["missing_output_assets"] == 1
    assert result["ready_for_assembly"] is False
