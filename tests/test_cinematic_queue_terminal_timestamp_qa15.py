"""QA 15: terminal queue updates must carry truthful public updated_at timestamps.

Exercises actual cinematic queue persistence in isolated SQLite workspace.
The worker is held; no FFmpeg, AI model inference, owner media, or device is used.
This is a test-first contract, not a claim that rendering or mobile UI failed.
"""
from __future__ import annotations

import importlib

import pytest

from app.studio.storage import connection
from test_cinematic_assembly_queue import HoldingPool, _ready_project


def _setup(monkeypatch, tmp_path):
    _, _, _, queue, project = _ready_project(monkeypatch, tmp_path)
    monkeypatch.setattr(queue, "assembly_pool", HoldingPool())
    request_type = importlib.import_module(
        "app.video.cinematic_requests"
    ).AssembleMasterRequest
    clock = [1_900_000_000.0]
    monkeypatch.setattr(queue, "_now", lambda: clock[0])
    return queue, project, request_type(expected_revision=project.revision), clock


def test_cancelled_job_exposes_its_last_transition_time(monkeypatch, tmp_path):
    """Control: cancellation already updates both SQLite and JSON timestamps."""
    queue, project, request, clock = _setup(monkeypatch, tmp_path)
    job = queue.enqueue_master_assembly(project.id, request)
    clock[0] += 11
    cancelled = queue.cancel_queued_master_assembly(project.id, job["id"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["updated_at"] == clock[0]
    assert queue.get_master_assembly_job(project.id, job["id"])["updated_at"] == clock[0]


@pytest.mark.parametrize("terminal_status", ["failed", "succeeded"])
def test_terminal_worker_status_updates_public_timestamp(
    monkeypatch, tmp_path, terminal_status,
):
    """The SQLite sort timestamp and returned job timestamp must agree.

    The terminal transition is injected directly: a synthetic succeeded state
    does NOT represent a verified master or a genuine FFmpeg render.
    """
    queue, project, request, clock = _setup(monkeypatch, tmp_path)
    job = queue.enqueue_master_assembly(project.id, request)

    clock[0] += 11
    claimed = queue._claim_next()
    assert claimed is not None and claimed["id"] == job["id"]
    assert claimed["updated_at"] == clock[0]

    clock[0] += 13
    result = queue._store_status(
        job["id"],
        status=terminal_status,
        stage="Synthetic terminal transition",
        finished_at=clock[0],
    )
    assert result is not None
    assert result["status"] == terminal_status

    with connection() as db:
        row = db.execute(
            "SELECT updated FROM records WHERE id=? AND kind=?",
            (job["id"], "video_assembly_job"),
        ).fetchone()
    assert row is not None and row[0] == clock[0]

    # The endpoint exposes JSON updated_at, not the SQLite updated column.
    # Currently it remains at the earlier claim time, so this contract is RED.
    persisted = queue.get_master_assembly_job(project.id, job["id"])
    assert persisted["updated_at"] == clock[0]
    assert result["updated_at"] == clock[0]
