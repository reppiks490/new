"""Long-film scheduling scale/restart QA using captured jobs, never GPU inference."""
from __future__ import annotations

import importlib

from PIL import Image


def test_600_second_60_shot_batch_pagination_then_restart(monkeypatch, tmp_path):
    """Every shot schedules once, in source order, despite bounded batches.

    A worker restart invalidates only in-flight jobs; the next batch retries
    earliest failed shots without erasing remaining shot or revision history.
    """
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    models = importlib.import_module("app.video.cinematic_models")
    requests = importlib.import_module("app.video.cinematic_requests")
    service = importlib.import_module("app.video.cinematic_service")
    storage = importlib.import_module("app.video.storage")
    engine = importlib.import_module("app.video.engine")
    jobs = importlib.import_module("app.video.jobs")

    monkeypatch.setattr(engine, "_ENGINE_REGISTRY", {})
    engine.register_engine(engine.FakeVideoEngine())

    class CapturePool:
        submitted = []
        def submit(self, fn, *args, **kwargs):
            self.submitted.append((fn, args, kwargs))
            return object()

    capture = CapturePool()
    monkeypatch.setattr(jobs, "pool", capture)
    image_id = "e" * 32
    Image.new("RGB", (24, 16), (10, 40, 60)).save(
        storage.video_asset_path(image_id, "png")
    )
    project = service.create_project(models.ProjectCreateRequest(
        title="60 shot QA film",
        master_prompt=(
            "SCENE 1: Arrival\nA figure enters an illuminated city.\n"
            "SCENE 2: Passage\nThe figure travels between distant buildings.\n"
            "SCENE 3: Dawn\nThe figure watches sunrise at the harbor."
        ),
        target_duration_seconds=600,
        delivery_fps=24,
        delivery_resolution="720p",
        reference_image_ids=[image_id],
        continuity_bible={"story_state": "NO_PRIVATE_TEXT_IN_JOB_STATUS"},
    ))
    project, diagnostics = service.compile_project(
        project.id,
        requests.CompileProjectRequest(
            expected_revision=1, preferred_shot_seconds=10,
            engine_max_duration_seconds=10, engine_name="fake",
        ),
    )
    shots = [shot for scene in project.scenes for shot in scene.shots]
    assert diagnostics["shot_count"] == len(shots) == 60
    assert sum(shot.duration_seconds for shot in shots) == 600

    all_ids = []
    revision = project.revision
    while len(all_ids) < len(shots):
        result = service.render_project_missing(
            project.id,
            requests.BatchRenderRequest(
                expected_revision=revision, engine_name="fake", max_shots=13,
            ),
        )
        scheduled = result["jobs"]
        assert scheduled
        assert len(scheduled) <= 13
        assert [job["shot_id"] for job in scheduled] == [
            shot.shot_id for shot in shots[len(all_ids):len(all_ids) + len(scheduled)]
        ]
        assert result["skipped"] == len(all_ids)
        assert result["project"]["revision"] == revision + len(scheduled)
        all_ids.extend(job["id"] for job in scheduled)
        revision = result["project"]["revision"]

    assert len(all_ids) == len(set(all_ids)) == 60
    assert len(capture.submitted) == 60
    first_status = service.project_render_status(project.id)
    assert first_status["total_shots"] == 60
    assert (first_status["active"], first_status["failed"], first_status["missing"]) == (60, 0, 0)
    assert first_status["ready_for_assembly"] is False
    assert "NO_PRIVATE_TEXT_IN_JOB_STATUS" not in str(first_status)

    assert jobs.interrupt_active_video_jobs() == 60
    restarted = service.project_render_status(project.id)
    assert (restarted["failed"], restarted["active"]) == (60, 0)
    # A bounded restart retry must not try to enqueue all 60 at once.
    retry = service.render_project_missing(
        project.id,
        requests.BatchRenderRequest(
            expected_revision=revision, engine_name="fake", max_shots=7,
        ),
    )
    assert [job["shot_id"] for job in retry["jobs"]] == [
        shot.shot_id for shot in shots[:7]
    ]
    assert retry["project"]["revision"] == revision + 7
    assert len(capture.submitted) == 67
    post_retry = service.project_render_status(project.id)
    assert (post_retry["active"], post_retry["failed"]) == (7, 53)
    assert post_retry["ready_for_assembly"] is False

    # All 60 shots remain in their original order. A replay never deletes or
    # overwrites source intent just because a worker lost active in-memory jobs.
    persisted = service.get_project(project.id)
    assert [shot.shot_id for scene in persisted.scenes for shot in scene.shots] == [
        shot.shot_id for shot in shots
    ]
    assert len(storage.list_video_records("video_job")) == 67
