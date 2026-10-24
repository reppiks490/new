"""QA38: recoverable partial failure in multi-shot local batch submission.

Uses the real SQLite-backed project, fake video engine and captured worker
submissions. No FFmpeg, model inference, owner footage or cloud service.
The strict test is opt-in so the ordinary CI suite stays green until a
lead-owned atomic-rollback or explicit partial-receipt policy is implemented.
"""
from __future__ import annotations

import importlib
import os

from PIL import Image
import pytest

STRICT = os.getenv("CINEMATIC_REQUIRE_BATCH_PARTIAL_RECEIPT_QA38") == "1"


class HoldingPool:
    def __init__(self):
        self.submissions = []

    def submit(self, fn, *args, **kwargs):
        self.submissions.append((fn, args, kwargs))
        return object()


@pytest.fixture
def batch_studio(monkeypatch, tmp_path):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path / "studio"))
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    requests = importlib.import_module("app.video.cinematic_requests")
    storage = importlib.import_module("app.video.storage")
    engine = importlib.import_module("app.video.engine")
    jobs = importlib.import_module("app.video.jobs")

    monkeypatch.setattr(engine, "_ENGINE_REGISTRY", {})
    engine.register_engine(engine.FakeVideoEngine())
    pool = HoldingPool()
    monkeypatch.setattr(jobs, "pool", pool)

    image_id = "a" * 32
    Image.new("RGB", (32, 24), (30, 50, 70)).save(
        storage.video_asset_path(image_id, "png")
    )
    project = service.create_project(models.ProjectCreateRequest(
        title="Synthetic batch recovery",
        master_prompt="Synthetic scene only, not owner screenplay.",
        target_duration_seconds=10,
        delivery_fps=24,
        delivery_resolution="480p",
        reference_image_ids=[image_id],
    ))
    shots = [
        models.CinematicShot(
            shot_id=f"{index + 100:032x}", ordinal=index + 1,
            title=f"Shot {index + 1}", prompt="Synthetic movement",
            duration_seconds=2,
        )
        for index in range(3)
    ]
    scene = models.CinematicScene(
        scene_id="b" * 32, ordinal=1, title="Synthetic scene",
        target_duration_seconds=6, shots=shots,
    )
    project = service.update_project(
        project.id,
        models.ProjectUpdateRequest(expected_revision=project.revision, scenes=[scene]),
    )
    return service, requests, storage, project, pool


def test_bounded_batch_success_has_discoverable_unscheduled_shots(batch_studio):
    """Control: a one-shot batch persists one job and leaves two discoverable."""
    service, requests, storage, project, pool = batch_studio
    result = service.render_project_missing(
        project.id, requests.BatchRenderRequest(
            expected_revision=project.revision, engine_name="fake", max_shots=1,
        ),
    )
    status = service.project_render_status(project.id)
    assert len(result["jobs"]) == 1
    assert len(pool.submissions) == 1
    assert result["project"]["revision"] == project.revision + 1
    assert (status["active"], status["missing"]) == (1, 2)
    assert len(storage.list_video_records("video_job")) == 1


@pytest.mark.skipif(
    not STRICT,
    reason="Strict expected-red partial-batch recovery contract runs in QA38 workflow",
)
def test_mid_batch_failure_is_atomic_or_returns_durable_partial_receipt(
    monkeypatch, batch_studio,
):
    """No silent partial write followed by an opaque exception and stale revision.

    Either the operation rolls back *all* first-shot changes, or the exception
    must carry a neutral durable job receipt and the current project revision.
    The existing implementation does neither.
    """
    service, requests, storage, project, pool = batch_studio
    original = service.render_shot
    calls = 0

    def fail_on_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic second-shot scheduling failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "render_shot", fail_on_second)
    with pytest.raises(RuntimeError) as raised:
        service.render_project_missing(
            project.id, requests.BatchRenderRequest(
                expected_revision=project.revision, engine_name="fake", max_shots=3,
            ),
        )

    persisted = service.get_project(project.id)
    jobs = storage.list_video_records("video_job")
    if persisted.revision == project.revision:
        # Accept only genuine atomic rollback, including the queued job record.
        assert jobs == []
        assert len(pool.submissions) == 0
    else:
        # A partial commit must be recoverable without guessing the new
        # revision or scanning private screenplay/shot prompt contents.
        assert persisted.revision == project.revision + 1
        assert len(jobs) == len(pool.submissions) == 1
        receipt = raised.value
        assert getattr(receipt, "current_revision", None) == persisted.revision, (
            "A failed batch advanced the project revision without a recovery receipt"
        )
        assert getattr(receipt, "submitted_job_ids", None) == [jobs[0]["id"]], (
            "A failed batch left a durable job without identifying it to the caller"
        )
        assert "Synthetic movement" not in str(receipt)
