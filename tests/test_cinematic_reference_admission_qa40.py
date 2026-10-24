"""QA40: local cinematic rendering must not enqueue malformed reference PNGs.

Application-level SQLite + fake-engine scheduling, not model inference.
Strict negative contracts are opt-in until the lead owns a production fix.
Only synthetic images are created inside pytest's temporary workspace.
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path

from PIL import Image
import pytest

STRICT = os.getenv("CINEMATIC_REQUIRE_REFERENCE_ADMISSION_QA40") == "1"
IMAGE_ID = "a" * 32
SCENE_ID = "b" * 32
SHOT_ID = "c" * 32


class HoldingPool:
    def __init__(self):
        self.calls = []

    def submit(self, fn, *args, **kwargs):
        self.calls.append((fn, args, kwargs))
        return object()


@pytest.fixture
def local_project(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    storage = importlib.import_module("app.video.storage")
    engine = importlib.import_module("app.video.engine")
    jobs = importlib.import_module("app.video.jobs")
    requests = importlib.import_module("app.video.cinematic_requests")
    audit = importlib.import_module("app.video.cinematic_reference_preflight")

    monkeypatch.setattr(engine, "_ENGINE_REGISTRY", {})
    engine.register_engine(engine.FakeVideoEngine())
    pool = HoldingPool()
    monkeypatch.setattr(jobs, "pool", pool)

    image = storage.video_asset_path(IMAGE_ID, "png")
    Image.new("RGB", (24, 16), (19, 38, 57)).save(image, format="PNG")
    created = service.create_project(models.ProjectCreateRequest(
        title="Synthetic reference admission",
        master_prompt="PRIVATE_QA40_SCREENPLAY_DO_NOT_ECHO",
        target_duration_seconds=10,
        reference_image_ids=[IMAGE_ID],
        delivery_fps=24,
        delivery_resolution="480p",
    ))
    shot = models.CinematicShot(
        shot_id=SHOT_ID, ordinal=1, title="Synthetic shot",
        prompt="Synthetic test camera motion", duration_seconds=5,
    )
    scene = models.CinematicScene(
        scene_id=SCENE_ID, ordinal=1, title="Synthetic scene",
        target_duration_seconds=5, shots=[shot],
    )
    project = service.update_project(
        created.id, models.ProjectUpdateRequest(
            expected_revision=1, scenes=[scene],
        ),
    )
    return service, storage, requests, audit, pool, project, image, tmp_path


def _render(ctx):
    service, _, requests, _, _, project, _, _ = ctx
    return service.render_shot(
        project.id, SCENE_ID, SHOT_ID,
        requests.ShotRenderRequest(
            expected_revision=project.revision, engine_name="fake",
        ),
    )


def _assert_no_side_effects(ctx):
    service, storage, _, _, pool, project, _, _ = ctx
    assert storage.list_video_records("video_job") == []
    assert service.get_project(project.id).revision == project.revision
    assert pool.calls == []


def test_valid_synthetic_png_admits_exactly_one_fake_engine_job(local_project):
    service, storage, _, audit, pool, project, _, workspace = local_project
    preflight = audit.audit_reference_files(project, workspace=workspace)
    assert preflight.references_ready
    result = _render(local_project)
    assert result["project"]["revision"] == project.revision + 1
    assert len(pool.calls) == 1
    assert len(storage.list_video_records("video_job")) == 1
    assert "PRIVATE_QA40_SCREENPLAY" not in str(result["job"])
    assert service.get_project(project.id).revision == project.revision + 1


@pytest.mark.skipif(
    not STRICT,
    reason="Expected-red production contract runs only in dedicated QA40 workflow",
)
def test_corrupted_png_must_be_rejected_before_sqlite_job_admission(local_project):
    _, _, _, audit, _, project, image, workspace = local_project
    image.write_bytes(b"synthetic-not-a-PNG-file")
    report = audit.audit_reference_files(project, workspace=workspace)
    assert not report.references_ready
    assert {finding.code for finding in report.findings} == {"REFERENCE_IMAGE_INVALID"}

    with pytest.raises((ValueError, OSError)):
        _render(local_project)
    _assert_no_side_effects(local_project)


@pytest.mark.skipif(
    not STRICT,
    reason="Expected-red production contract runs only in dedicated QA40 workflow",
)
def test_oversized_png_must_be_rejected_before_sqlite_job_admission(local_project):
    _, _, _, audit, _, project, image, workspace = local_project
    # Sparse growth avoids allocating 12 MiB of synthetic test data.
    with image.open("ab") as handle:
        handle.truncate(12 * 1024 * 1024 + 1)
    report = audit.audit_reference_files(project, workspace=workspace)
    assert not report.references_ready
    assert {finding.code for finding in report.findings} == {"REFERENCE_TOO_MANY_BYTES"}

    with pytest.raises((ValueError, OSError)):
        _render(local_project)
    _assert_no_side_effects(local_project)
