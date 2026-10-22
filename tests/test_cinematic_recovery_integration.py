"""Cinematic batch/restart/failure regression tests.

All jobs use the fake local engine and a capture-only pool. No GPU execution,
FFmpeg installation, external providers, or purchased inference is required.
"""
from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image


REFERENCE_ID = "0" * 32
SCENE_ID = "2" * 32


class CapturePool:
    def __init__(self):
        self.submissions = []

    def submit(self, fn, *args, **kwargs):
        self.submissions.append((fn, args, kwargs))
        return object()


def _setup(monkeypatch, tmp_path: Path, *, count: int = 3):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("CHARACTER3D_STUDIO_TOKEN", raising=False)

    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    requests = importlib.import_module("app.video.cinematic_requests")
    storage = importlib.import_module("app.video.storage")
    engine = importlib.import_module("app.video.engine")
    jobs = importlib.import_module("app.video.jobs")

    monkeypatch.setattr(engine, "_ENGINE_REGISTRY", {})
    engine.register_engine(engine.FakeVideoEngine())
    pool = CapturePool()
    monkeypatch.setattr(jobs, "pool", pool)

    Image.new("RGB", (24, 16), (17, 32, 49)).save(
        storage.video_asset_path(REFERENCE_ID, "png")
    )
    created = service.create_project(
        models.ProjectCreateRequest(
            title="Private recovery test",
            master_prompt="MASTER_SCRIPT_NEVER_INCLUDE_IN_STATUS",
            target_duration_seconds=max(10, count * 5),
            delivery_fps=24,
            delivery_resolution="720p",
            continuity_bible={"wardrobe": "PRIVATE_WARDROBE_SENTINEL"},
            reference_image_ids=[REFERENCE_ID],
        )
    )
    shots = [
        models.CinematicShot(
            shot_id=f"{32 + i:032x}",
            ordinal=i + 1,
            title=f"Neutral shot {i + 1}",
            prompt=f"SECRET_SHOT_{i + 1} cinematic movement",
            duration_seconds=5,
        )
        for i in range(count)
    ]
    scene = models.CinematicScene(
        scene_id=SCENE_ID,
        ordinal=1,
        title="Exterior",
        source_text="SECRET_SCENE_TEXT",
        target_duration_seconds=count * 5,
        shots=shots,
    )
    project = service.update_project(
        created.id,
        models.ProjectUpdateRequest(expected_revision=1, scenes=[scene]),
    )
    return SimpleNamespace(
        models=models, service=service, requests=requests, storage=storage,
        jobs=jobs, project=project, pool=pool,
    )


def _batch(ctx, revision, max_shots=10):
    return ctx.service.render_project_missing(
        ctx.project.id,
        ctx.requests.BatchRenderRequest(
            expected_revision=revision, engine_name="fake", max_shots=max_shots
        ),
    )


def test_restart_changes_queued_to_failed_then_resume_without_duplicate_jobs(
    monkeypatch, tmp_path
):
    ctx = _setup(monkeypatch, tmp_path, count=3)
    first = _batch(ctx, revision=2, max_shots=2)
    original_ids = [item["id"] for item in first["jobs"]]
    assert len(original_ids) == 2
    assert [item["shot_id"] for item in first["jobs"]] == [
        shot.shot_id for shot in ctx.project.scenes[0].shots[:2]
    ]
    assert first["project"]["revision"] == 4
    assert len(ctx.pool.submissions) == 2

    before = ctx.service.project_render_status(ctx.project.id)
    assert (before["active"], before["missing"], before["failed"]) == (2, 1, 0)
    interrupted = ctx.jobs.interrupt_active_video_jobs()
    assert interrupted == 2
    after = ctx.service.project_render_status(ctx.project.id)
    assert (after["active"], after["missing"], after["failed"]) == (0, 1, 2)
    assert after["ready_for_assembly"] is False

    # Bounded recovery first retries the earliest failed shot.
    retry_one = _batch(ctx, revision=4, max_shots=1)
    assert len(retry_one["jobs"]) == 1
    assert retry_one["jobs"][0]["shot_id"] == ctx.project.scenes[0].shots[0].shot_id
    assert retry_one["jobs"][0]["id"] != original_ids[0]
    assert retry_one["project"]["revision"] == 5

    # Retry the remaining failed shot and schedule the never-started shot.
    retry_rest = _batch(ctx, revision=5, max_shots=2)
    assert len(retry_rest["jobs"]) == 2
    assert [item["shot_id"] for item in retry_rest["jobs"]] == [
        shot.shot_id for shot in ctx.project.scenes[0].shots[1:]
    ]
    assert retry_rest["project"]["revision"] == 7
    assert len(ctx.pool.submissions) == 5
    all_active = ctx.service.project_render_status(ctx.project.id)
    assert (all_active["active"], all_active["failed"], all_active["missing"]) == (3, 0, 0)

    # Another request is strictly idempotent, without advancing the revision.
    noop = _batch(ctx, revision=7)
    assert noop["jobs"] == []
    assert noop["skipped"] == 3
    assert noop["project"]["revision"] == 7
    assert len(ctx.pool.submissions) == 5
    assert ctx.jobs.interrupt_active_video_jobs() == 3

    # The API status surface must be neutral even when screenplay and
    # continuity have explicit private sentinels.
    assert "MASTER_SCRIPT_NEVER_INCLUDE_IN_STATUS" not in str(all_active)
    assert "PRIVATE_WARDROBE_SENTINEL" not in str(all_active)
    assert "SECRET_SHOT_" not in str(all_active)


def test_restart_never_requeues_completed_shot_with_existing_local_asset(
    monkeypatch, tmp_path
):
    ctx = _setup(monkeypatch, tmp_path, count=3)
    first = _batch(ctx, revision=2)
    completed_job = first["jobs"][0]
    video_id = "f" * 32
    ctx.storage.video_asset_path(video_id, "mp4").write_bytes(
        b"\x00\x00\x00\x18ftypmp42test-video"
    )
    ctx.jobs._update_job(
        completed_job["id"], status="succeeded", stage="Ready", progress=100,
        asset_id=video_id, asset_url=f"/api/video/assets/{video_id}.mp4",
    )
    assert ctx.jobs.interrupt_active_video_jobs() == 2

    current = ctx.service.project_render_status(ctx.project.id)
    assert (current["succeeded"], current["failed"]) == (1, 2)
    assert current["ready_for_assembly"] is False
    recovered = _batch(ctx, revision=5)
    assert len(recovered["jobs"]) == 2
    assert [job["shot_id"] for job in recovered["jobs"]] == [
        shot.shot_id for shot in ctx.project.scenes[0].shots[1:]
    ]
    first_link = ctx.service.get_project(ctx.project.id).scenes[0].shots[0].latest_job_id
    assert first_link == completed_job["id"]


def test_stale_batch_cannot_schedule_jobs_or_advance_revision(monkeypatch, tmp_path):
    ctx = _setup(monkeypatch, tmp_path, count=2)
    first = _batch(ctx, revision=2, max_shots=1)
    total_before = len(ctx.storage.list_video_records("video_job"))
    with pytest.raises(ctx.service.ProjectRevisionConflict):
        _batch(ctx, revision=2, max_shots=2)
    assert len(ctx.storage.list_video_records("video_job")) == total_before
    assert ctx.service.get_project(ctx.project.id).revision == first["project"]["revision"]
    assert len(ctx.pool.submissions) == 1


def test_foreign_job_link_is_ignored_and_correctly_rescheduled(monkeypatch, tmp_path):
    ctx = _setup(monkeypatch, tmp_path, count=1)
    original_shot = ctx.project.scenes[0].shots[0]
    forged = ctx.storage.put_video_record("video_job", {
        "status": "succeeded",
        "project_id": "d" * 32,
        "scene_id": SCENE_ID,
        "shot_id": original_shot.shot_id,
        "asset_id": "f" * 32,
    })
    edited_scene = ctx.project.scenes[0].model_copy(update={
        "shots": [original_shot.model_copy(update={"latest_job_id": forged["id"]})]
    })
    updated = ctx.service.update_project(
        ctx.project.id,
        ctx.models.ProjectUpdateRequest(
            expected_revision=2, scenes=[edited_scene]
        ),
    )
    status = ctx.service.project_render_status(ctx.project.id)
    assert status["missing"] == 1
    assert status["succeeded"] == 0
    assert status["ready_for_assembly"] is False
    result = _batch(ctx, revision=updated.revision)
    assert len(result["jobs"]) == 1
    assert result["jobs"][0]["id"] != forged["id"]
    assert result["jobs"][0]["project_id"] == ctx.project.id


@pytest.mark.parametrize("return_code,output_bytes", [
    (5, b"\x00\x00\x00\x18ftypmp42partial"),
    (0, b"not-an-mp4-container"),
])
def test_failed_or_corrupt_master_never_publishes_partial_asset(
    monkeypatch, tmp_path, return_code, output_bytes
):
    ctx = _setup(monkeypatch, tmp_path, count=1)
    shot = ctx.project.scenes[0].shots[0]
    video_id = "a" * 32
    source = ctx.storage.video_asset_path(video_id, "mp4")
    source.write_bytes(b"\x00\x00\x00\x18ftypmp42source")
    job = ctx.storage.put_video_record("video_job", {
        "status": "succeeded",
        "project_id": ctx.project.id,
        "scene_id": SCENE_ID,
        "shot_id": shot.shot_id,
        "project_revision": 2,
        "asset_id": video_id,
        "fps": 24,
        "resolution": "720p",
        "duration_seconds": 5,
    })
    linked = shot.model_copy(update={"latest_job_id": job["id"]})
    scene = ctx.project.scenes[0].model_copy(update={"shots": [linked]})
    project = ctx.service.update_project(
        ctx.project.id,
        ctx.models.ProjectUpdateRequest(expected_revision=2, scenes=[scene]),
    )
    seen = []

    def fake_ffmpeg(command, **_):
        seen.append(command)
        Path(command[-1]).write_bytes(output_bytes)
        return SimpleNamespace(returncode=return_code, stdout="", stderr="")

    monkeypatch.setattr(ctx.service, "_run_master_ffmpeg", fake_ffmpeg)
    with pytest.raises(RuntimeError):
        ctx.service.assemble_project_master(
            ctx.project.id,
            ctx.requests.AssembleMasterRequest(expected_revision=project.revision),
        )
    assert len(seen) == 1
    assert source.exists()
    assert list(ctx.storage.list_video_records("video_master")) == []
    assert [file for file in (tmp_path / "video-assets").glob("*.mp4")] == [source]
    assert ctx.service.get_project(ctx.project.id).revision == project.revision


def test_worker_submit_rejection_leaves_retryable_failed_job_and_no_active_orphan(
    monkeypatch, tmp_path
):
    """Worker exhaustion after a successful link must fail visibly and retry."""
    ctx = _setup(monkeypatch, tmp_path, count=1)
    engine = importlib.import_module("app.video.engine")

    class RejectPool:
        def submit(self, *_args, **_kwargs):
            raise RuntimeError("worker unavailable")

    monkeypatch.setattr(ctx.jobs, "pool", RejectPool())
    with pytest.raises(engine.EngineUnavailableError):
        _batch(ctx, revision=2)

    saved = ctx.service.get_project(ctx.project.id)
    assert saved.revision == 3
    failed_id = saved.scenes[0].shots[0].latest_job_id
    assert failed_id
    failure = ctx.storage.get_video_record("video_job", failed_id)
    assert failure["status"] == "failed"
    assert failure["stage"] == "Stopped"
    assert "worker unavailable" not in str(failure).lower()
    state = ctx.service.project_render_status(ctx.project.id)
    assert (state["failed"], state["active"], state["succeeded"]) == (1, 0, 0)
    assert state["ready_for_assembly"] is False

    # A recovered worker retries the failed link instead of preserving a
    # terminally unusable success state or producing two active jobs.
    monkeypatch.setattr(ctx.jobs, "pool", ctx.pool)
    retry = _batch(ctx, revision=3)
    assert len(retry["jobs"]) == 1
    assert retry["jobs"][0]["id"] != failed_id
    assert retry["project"]["revision"] == 4
    assert len(ctx.pool.submissions) == 1
    state = ctx.service.project_render_status(ctx.project.id)
    assert (state["failed"], state["active"], state["succeeded"]) == (0, 1, 0)


def test_concurrent_same_revision_shot_submissions_only_one_wins(
    monkeypatch, tmp_path
):
    """CAS race must cancel the losing queued job before GPU submission."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    ctx = _setup(monkeypatch, tmp_path, count=1)
    target = ctx.project.scenes[0].shots[0]
    barrier = threading.Barrier(2)
    original_update = ctx.service.update_project

    def synchronized_update(project_id, request):
        if project_id == ctx.project.id and request.expected_revision == 2:
            barrier.wait(timeout=20)
        return original_update(project_id, request)

    monkeypatch.setattr(ctx.service, "update_project", synchronized_update)

    def attempt():
        try:
            result = ctx.service.render_shot(
                ctx.project.id, SCENE_ID, target.shot_id,
                ctx.requests.ShotRenderRequest(
                    expected_revision=2, engine_name="fake"
                ),
            )
            return ("ok", result["job"]["id"])
        except ctx.service.ProjectRevisionConflict:
            return ("conflict", None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: attempt(), range(2)))

    assert sorted(state for state, _ in outcomes) == ["conflict", "ok"]
    records = ctx.storage.list_video_records("video_job")
    assert len(records) == 2
    assert sum(record["status"] == "queued" for record in records) == 1
    assert sum(record["status"] == "failed" for record in records) == 1
    assert len(ctx.pool.submissions) == 1
    saved = ctx.service.get_project(ctx.project.id)
    assert saved.revision == 3
    assert saved.scenes[0].shots[0].latest_job_id == next(
        job["id"] for job in records if job["status"] == "queued"
    )
    status = ctx.service.project_render_status(ctx.project.id)
    assert (status["active"], status["failed"], status["succeeded"]) == (1, 0, 0)


def test_missing_source_image_creates_no_job_or_revision_change(
    monkeypatch, tmp_path
):
    """Failure before linking must neither consume a revision nor enqueue work."""
    ctx = _setup(monkeypatch, tmp_path, count=1)
    source = ctx.storage.video_asset_path(REFERENCE_ID, "png")
    image_bytes = source.read_bytes()
    source.unlink()

    with pytest.raises(FileNotFoundError):
        _batch(ctx, revision=2)
    assert ctx.service.get_project(ctx.project.id).revision == 2
    assert ctx.storage.list_video_records("video_job") == []
    assert ctx.pool.submissions == []

    # Make the original authorized source available; retry resumes normally.
    source.write_bytes(image_bytes)
    outcome = _batch(ctx, revision=2)
    assert len(outcome["jobs"]) == 1
    assert outcome["project"]["revision"] == 3
    assert len(ctx.pool.submissions) == 1
