"""Regression contract: edited cinematic intent must not reuse obsolete MP4s.

Hermetic: locally stored MP4 signatures and captured fake-engine submissions.
No FFmpeg, GPU, private media, network activity or paid provider calls.
"""
from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest
from PIL import Image

IMAGE = "a" * 32
SCENE = "1" * 32
SHOT_A = "2" * 32
SHOT_B = "3" * 32


def _ready(monkeypatch, tmp_path):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    storage = importlib.import_module("app.video.storage")
    requests = importlib.import_module("app.video.cinematic_requests")
    Image.new("RGB", (20, 20), (9, 20, 44)).save(
        storage.video_asset_path(IMAGE, "png")
    )
    project = service.create_project(models.ProjectCreateRequest(
        title="Editorial title",
        master_prompt="PRIVATE_STORY_KEYCARD first act",
        target_duration_seconds=10,
        delivery_fps=24,
        delivery_resolution="720p",
        reference_image_ids=[IMAGE],
    ))
    scene = models.CinematicScene(
        scene_id=SCENE, ordinal=1, title="Chapter",
        target_duration_seconds=10, shots=[
            models.CinematicShot(
                shot_id=SHOT_A, ordinal=1, title="A",
                prompt="ACTION_ALPHA", duration_seconds=5,
            ),
            models.CinematicShot(
                shot_id=SHOT_B, ordinal=2, title="B",
                prompt="ACTION_BETA", duration_seconds=5,
            ),
        ],
    )
    project = service.update_project(
        project.id,
        models.ProjectUpdateRequest(expected_revision=1, scenes=[scene]),
    )
    old_jobs = []
    linked = []
    for index, shot in enumerate(project.scenes[0].shots, start=1):
        asset_id = f"{index + 8:032x}"
        storage.video_asset_path(asset_id, "mp4").write_bytes(
            b"\x00\x00\x00\x18ftypmp42source"
        )
        record = storage.put_video_record("video_job", {
            "status": "succeeded",
            "project_id": project.id,
            "project_revision": 2,
            "scene_id": SCENE,
            "shot_id": shot.shot_id,
            "asset_id": asset_id,
        })
        old_jobs.append(record)
        linked.append(shot.model_copy(update={
            "latest_job_id": record["id"],
            "latest_asset_url": f"/api/video/assets/{asset_id}.mp4",
            "latest_rendered_project_revision": 2,
        }))
    project = service.update_project(project.id, models.ProjectUpdateRequest(
        expected_revision=2,
        scenes=[project.scenes[0].model_copy(update={"shots": linked})],
    ))
    status = service.project_render_status(project.id)
    assert status["succeeded"] == 2
    assert status["ready_for_assembly"] is True
    return SimpleNamespace(
        models=models, service=service, storage=storage,
        requests=requests, project=project, old_jobs=old_jobs,
    )


def _update(ctx, *, first=None, scene=None, **patch):
    current = ctx.service.get_project(ctx.project.id)
    edited_scene = scene or current.scenes[0]
    if first is not None:
        edited_scene = edited_scene.model_copy(update={
            "shots": [first, edited_scene.shots[1]],
        })
    data = {"expected_revision": current.revision, **patch}
    if "scenes" not in data:
        data["scenes"] = [edited_scene]
    return ctx.service.update_project(
        current.id, ctx.models.ProjectUpdateRequest(**data),
    )


@pytest.mark.parametrize("change", [
    "prompt", "negative_prompt", "seed", "duration_seconds",
    "motion_strength", "camera_motion", "shot_continuity",
    "shot_reference", "scene_continuity", "scene_source",
])
def test_editing_only_one_shot_detaches_only_its_stale_render(
    monkeypatch, tmp_path, change,
):
    ctx = _ready(monkeypatch, tmp_path)
    scene = ctx.project.scenes[0]
    first = scene.shots[0]
    if change == "shot_continuity":
        first = first.model_copy(update={
            "continuity_patch": ctx.models.ContinuityPatch(
                wardrobe="SECOND_WARDROBE",
            ),
        })
    elif change == "shot_reference":
        first = first.model_copy(update={
            "reference_image_ids": ["e" * 32],
        })
    elif change == "scene_continuity":
        scene = scene.model_copy(update={
            "continuity_patch": ctx.models.ContinuityPatch(
                lighting="NEW_LIGHTING",
            ),
        })
        # Scene-wide continuity genuinely affects both shots.
        revised = _update(ctx, scene=scene)
        assert all(not shot.latest_job_id for shot in revised.scenes[0].shots)
        assert ctx.service.project_render_status(ctx.project.id)["succeeded"] == 0
        return
    elif change == "scene_source":
        scene = scene.model_copy(update={
            "source_text": "New scene instructions",
        })
        revised = _update(ctx, scene=scene)
        assert all(not shot.latest_job_id for shot in revised.scenes[0].shots)
        return
    else:
        changes = {
            "prompt": "ACTION_ALPHA_AFTER_EDIT",
            "negative_prompt": "Avoid glare",
            "seed": 701,
            "duration_seconds": 4,
            "motion_strength": 0.6,
            "camera_motion": "pan_left",
        }
        first = first.model_copy(update={change: changes[change]})

    revised = _update(ctx, first=first)
    modified, original = revised.scenes[0].shots
    assert modified.latest_job_id is None
    assert modified.latest_asset_url is None
    assert modified.latest_rendered_project_revision is None
    assert original.latest_job_id == ctx.old_jobs[1]["id"]
    assert ctx.storage.get_video_record(
        "video_job", ctx.old_jobs[0]["id"]
    )["status"] == "succeeded"
    status = ctx.service.project_render_status(ctx.project.id)
    assert (status["succeeded"], status["missing"]) == (1, 1)
    assert status["ready_for_assembly"] is False
    assert "PRIVATE_STORY_KEYCARD" not in str(status)


def test_retry_only_changed_shot_without_duplicate_completed_job(monkeypatch, tmp_path):
    ctx = _ready(monkeypatch, tmp_path)
    first = ctx.project.scenes[0].shots[0].model_copy(update={
        "prompt": "New camera choreography",
    })
    revised = _update(ctx, first=first)
    engine = importlib.import_module("app.video.engine")
    jobs = importlib.import_module("app.video.jobs")
    monkeypatch.setattr(engine, "_ENGINE_REGISTRY", {})
    engine.register_engine(engine.FakeVideoEngine())

    class CapturePool:
        submitted = []
        def submit(self, *args, **kwargs):
            self.submitted.append((args, kwargs))
            return object()

    capture = CapturePool()
    monkeypatch.setattr(jobs, "pool", capture)
    result = ctx.service.render_project_missing(
        ctx.project.id, ctx.requests.BatchRenderRequest(
            expected_revision=revised.revision, engine_name="fake",
        ),
    )
    assert len(result["jobs"]) == 1
    assert result["jobs"][0]["shot_id"] == SHOT_A
    assert result["jobs"][0]["id"] != ctx.old_jobs[0]["id"]
    assert len(capture.submitted) == 1
    assert ctx.service.get_project(ctx.project.id).scenes[0].shots[1].latest_job_id == (
        ctx.old_jobs[1]["id"]
    )


def test_project_title_change_does_not_invalidate_expensive_good_media(monkeypatch, tmp_path):
    ctx = _ready(monkeypatch, tmp_path)
    new = _update(ctx, title="New distribution title")
    assert new.revision == ctx.project.revision + 1
    assert [shot.latest_job_id for shot in new.scenes[0].shots] == [
        record["id"] for record in ctx.old_jobs
    ]
    status = ctx.service.project_render_status(new.id)
    assert status["ready_for_assembly"] is True
    assert status["succeeded"] == 2


@pytest.mark.parametrize("global_edit", [
    "master_prompt", "delivery_fps", "delivery_resolution",
    "project_continuity", "project_references",
])
def test_render_affecting_project_change_conservatively_invalidates_all(
    monkeypatch, tmp_path, global_edit
):
    ctx = _ready(monkeypatch, tmp_path)
    if global_edit == "project_continuity":
        patch = {"continuity_bible": ctx.models.ContinuityState(
            characters="NEW_CAST",
        )}
    elif global_edit == "project_references":
        patch = {"reference_image_ids": ["e" * 32]}
    else:
        patch = {global_edit: {
            "master_prompt": "Second screenplay version",
            "delivery_fps": 30,
            "delivery_resolution": "1080p",
        }[global_edit]}
    new = _update(ctx, **patch)
    assert all(shot.latest_job_id is None for shot in new.scenes[0].shots)
    assert ctx.service.project_render_status(new.id)["ready_for_assembly"] is False


def test_new_shot_cannot_import_old_completed_job_link(monkeypatch, tmp_path):
    ctx = _ready(monkeypatch, tmp_path)
    scene = ctx.project.scenes[0]
    forged_shot = scene.shots[0].model_copy(update={
        "shot_id": "f" * 32, "ordinal": 3,
        "latest_job_id": ctx.old_jobs[0]["id"],
    })
    new_scene = scene.model_copy(update={"shots": [*scene.shots, forged_shot]})
    revised = _update(ctx, scene=new_scene)
    assert revised.scenes[0].shots[-1].latest_job_id is None
    assert ctx.service.project_render_status(ctx.project.id)["missing"] == 1
