"""Independent fail-closed contract QA for durable cinematic master jobs.

A plausible FFmpeg/master result must be bound to the queued project and
revision, not merely match the shape of an asset URL and a SHA-256 string.
Synthetic job results only: never reads owner footage or calls FFmpeg.
"""
from __future__ import annotations

import importlib

import pytest

from test_cinematic_assembly_queue import HoldingPool, _ready_project


@pytest.mark.parametrize(
    "tamper",
    [
        pytest.param({"project_id": "f" * 32}, id="different-project"),
        pytest.param({"project_revision": 9999}, id="different-revision"),
        pytest.param({"project_id": None, "project_revision": None}, id="missing-ownership"),
    ],
)
def test_async_assembly_never_publishes_unbound_verified_looking_master(
    monkeypatch, tmp_path, tamper,
):
    _, _, _, queue, project = _ready_project(monkeypatch, tmp_path)
    monkeypatch.setattr(queue, "assembly_pool", HoldingPool())
    request_type = importlib.import_module(
        "app.video.cinematic_requests"
    ).AssembleMasterRequest
    job = queue.enqueue_master_assembly(
        project.id, request_type(expected_revision=project.revision)
    )

    # This passes the current shape/probe/hash checks. Its project/revision
    # binding, however, disagrees with the durable queued job.
    fabricated = {
        "id": "b" * 32,
        "asset_id": "a" * 32,
        "asset_url": "/api/video/assets/" + "a" * 32 + ".mp4",
        "status": "ready",
        "probe": {"probe_metadata_verified": True},
        "actual_video_probe_verified": True,
        "sha256": "e" * 64,
        "project_id": project.id,
        "project_revision": project.revision,
    }
    fabricated.update(tamper)
    monkeypatch.setattr(
        queue, "assemble_project_master", lambda *_args, **_kwargs: fabricated
    )

    queue._drain()
    final = queue.get_master_assembly_job(project.id, job["id"])
    assert final["status"] == "failed", (
        "A master belonging to another/missing project revision was accepted"
    )
    assert final["stage"] == "Assembly failed"
    assert "asset_id" not in final
    assert "asset_url" not in final
    assert "sha256" not in final
    assert "PRIVATE" not in str(final)


@pytest.mark.parametrize(
    "persisted",
    [
        pytest.param("missing", id="no-persisted-master"),
        pytest.param("wrong-asset", id="persisted-asset-mismatch"),
        pytest.param("wrong-sha", id="persisted-sha-mismatch"),
        pytest.param("wrong-project", id="persisted-project-mismatch"),
        pytest.param("wrong-revision", id="persisted-revision-mismatch"),
    ],
)
def test_async_assembly_requires_matching_persisted_master_record(
    monkeypatch, tmp_path, persisted,
):
    """A truthful-looking return value alone is not persisted media evidence."""
    _, _, storage, queue, project = _ready_project(monkeypatch, tmp_path)
    monkeypatch.setattr(queue, "assembly_pool", HoldingPool())
    request_type = importlib.import_module(
        "app.video.cinematic_requests"
    ).AssembleMasterRequest
    job = queue.enqueue_master_assembly(
        project.id, request_type(expected_revision=project.revision)
    )
    result = {
        "id": "b" * 32,
        "asset_id": "a" * 32,
        "asset_url": "/api/video/assets/" + "a" * 32 + ".mp4",
        "status": "ready",
        "probe": {"probe_metadata_verified": True},
        "actual_video_probe_verified": True,
        "sha256": "e" * 64,
        "project_id": project.id,
        "project_revision": project.revision,
    }
    if persisted != "missing":
        stored = dict(result)
        if persisted == "wrong-asset":
            stored["asset_id"] = "c" * 32
        elif persisted == "wrong-sha":
            stored["sha256"] = "d" * 64
        elif persisted == "wrong-project":
            stored["project_id"] = "f" * 32
        elif persisted == "wrong-revision":
            stored["project_revision"] = project.revision + 1
        storage.put_video_record("video_master", stored, identifier=result["id"])

    monkeypatch.setattr(
        queue, "assemble_project_master", lambda *_args, **_kwargs: result
    )
    queue._drain()
    final = queue.get_master_assembly_job(project.id, job["id"])
    assert final["status"] == "failed", (
        "Unpersisted or mismatched master result was published as ready"
    )
    assert final["stage"] == "Assembly failed"
    assert "asset_id" not in final
    assert "asset_url" not in final
    assert "sha256" not in final
    assert "VERY_PRIVATE" not in str(final)
