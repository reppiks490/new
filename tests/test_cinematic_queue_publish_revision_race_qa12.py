"""QA 12: a master must not become a successful queue result after its project changes.

Synthetic SQLite + mocked assembler only. This isolates the gap AFTER a valid
assembler return but BEFORE the durable queue publishes success; no FFmpeg,
model inference, real owner media or mobile device is exercised.
"""
from __future__ import annotations

import hashlib
import importlib

import pytest

from test_cinematic_assembly_queue import HoldingPool, _ready_project


@pytest.mark.parametrize(
    "edit",
    [
        pytest.param("creative", id="creative-input-edited-after-assembly"),
        pytest.param("metadata", id="project-title-edited-after-assembly"),
    ],
)
def test_queue_rechecks_current_project_revision_before_publishing_master(
    monkeypatch, tmp_path, edit,
):
    service, _, storage, queue, project = _ready_project(monkeypatch, tmp_path)
    monkeypatch.setattr(queue, "assembly_pool", HoldingPool())
    request_type = importlib.import_module(
        "app.video.cinematic_requests"
    ).AssembleMasterRequest
    models = importlib.import_module("app.video.cinematic_models")

    queued = queue.enqueue_master_assembly(
        project.id, request_type(expected_revision=project.revision)
    )
    # The assembler's returned record is internally consistent and belongs to
    # the originally queued revision. The race is an edit after that result.
    asset_id = "c" * 32
    media = b"\x00\x00\x00\x18ftypmp42synthetic-queue-revision-test"
    storage.video_asset_path(asset_id, "mp4").write_bytes(media)
    persisted = storage.put_video_record(
        "video_master",
        {
            "status": "ready",
            "project_id": project.id,
            "project_revision": project.revision,
            "asset_id": asset_id,
            "asset_url": f"/api/video/assets/{asset_id}.mp4",
            "sha256": hashlib.sha256(media).hexdigest(),
            "actual_video_probe_verified": True,
            "probe": {"probe_metadata_verified": True},
        },
        identifier="d" * 32,
    )

    def assembler_then_owner_edit(*_args, **_kwargs):
        changes = (
            {"master_prompt": "Private revised scene direction"}
            if edit == "creative"
            else {"title": "Private retitled film"}
        )
        updated = service.update_project(
            project.id,
            models.ProjectUpdateRequest(
                expected_revision=project.revision, **changes
            ),
        )
        assert updated.revision == project.revision + 1
        return persisted

    monkeypatch.setattr(queue, "assemble_project_master", assembler_then_owner_edit)
    queue._drain()

    result = queue.get_master_assembly_job(project.id, queued["id"])
    assert service.get_project(project.id).revision == project.revision + 1
    assert result["status"] == "failed", (
        "Queue published a verified-looking master for an obsolete project "
        "revision after the owner edited the project"
    )
    assert result["stage"] == "Stale revision"
    assert "master_id" not in result
    assert "asset_id" not in result
    assert "asset_url" not in result
    assert "sha256" not in result
    assert "VERY_PRIVATE_UNRENDERED_SCRIPT" not in str(result)
