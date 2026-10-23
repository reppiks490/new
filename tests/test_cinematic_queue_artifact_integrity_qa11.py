"""QA 11: a durable assembly job must not advertise absent or changed master bytes.

This is a synthetic metadata / SQLite contract test, not an FFmpeg or model
inference test. The deliberately fabricated assembler return is used only to
exercise the trust boundary between the assembler and the durable queue.
"""
from __future__ import annotations

import importlib

import pytest

from test_cinematic_assembly_queue import HoldingPool, _ready_project


@pytest.mark.parametrize(
    "media_state",
    [
        pytest.param("missing", id="master-file-deleted-before-queue-publication"),
        pytest.param("wrong-bytes", id="master-file-changed-before-queue-publication"),
    ],
)
def test_queue_rejects_persisted_master_without_matching_on_disk_bytes(
    monkeypatch, tmp_path, media_state,
):
    _, _, storage, queue, project = _ready_project(monkeypatch, tmp_path)
    monkeypatch.setattr(queue, "assembly_pool", HoldingPool())
    request_type = importlib.import_module(
        "app.video.cinematic_requests"
    ).AssembleMasterRequest
    queued = queue.enqueue_master_assembly(
        project.id, request_type(expected_revision=project.revision)
    )

    master_id = "b" * 32
    asset_id = "a" * 32
    path = storage.video_asset_path(asset_id, "mp4")
    if media_state == "wrong-bytes":
        # Bytes are intentionally synthetic and not a valid FFmpeg deliverable.
        # The persisted SHA below explicitly does not describe these bytes.
        path.write_bytes(b"synthetic-media-bytes-that-do-not-match-declared-sha")

    persisted = storage.put_video_record(
        "video_master",
        {
            "status": "ready",
            "project_id": project.id,
            "project_revision": project.revision,
            "asset_id": asset_id,
            "asset_url": f"/api/video/assets/{asset_id}.mp4",
            "sha256": "f" * 64,
            "actual_video_probe_verified": True,
            "probe": {"probe_metadata_verified": True},
        },
        identifier=master_id,
    )
    # The assembler would normally have produced/verified the bytes. This
    # isolates deletion or replacement between its return and queue publish.
    monkeypatch.setattr(
        queue, "assemble_project_master", lambda *_args, **_kwargs: persisted
    )
    queue._drain()
    final = queue.get_master_assembly_job(project.id, queued["id"])

    assert final["status"] == "failed", (
        "Queue advertised succeeded using matching SQLite metadata despite "
        f"{media_state} on-disk master media"
    )
    assert final["stage"] == "Assembly failed"
    assert "asset_id" not in final
    assert "asset_url" not in final
    assert "sha256" not in final
    assert "VERY_PRIVATE_UNRENDERED_SCRIPT" not in str(final)
