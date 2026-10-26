"""QA89: terminal assembly timestamps must describe one serialized transition.

Synthetic SQLite only; no FFmpeg, inference, owner media or physical mobile test.
Frozen parent QA88 #184 c4efc29c8a18382dca3d9198355eaeef7c1a287e.
"""
from __future__ import annotations

import importlib
import json

import pytest


@pytest.mark.parametrize("terminal", ["succeeded", "failed"])
@pytest.mark.parametrize("clock_advances", [False, True], ids=["same-clock-control", "prelock-finish-stale"])
def test_terminal_finish_time_matches_committed_history(
    monkeypatch, tmp_path, terminal, clock_advances
):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    queue = importlib.import_module("app.video.cinematic_assembly_jobs")
    identifier, project_id = "a" * 32, "b" * 32
    payload = {
        "project_id": project_id,
        "project_revision": 3,
        "status": "running",
        "stage": "Assembling",
        "started_at": 100.0,
        "updated_at": 100.0,
        "progress": None,
    }
    with queue.connection() as db:
        db.execute(
            "INSERT INTO records(id,kind,data,updated) VALUES(?,?,?,?)",
            (identifier, "video_assembly_job", json.dumps(payload), 100.0),
        )

    # Simulates _execute_one computing finished_at before _store_status
    # acquires BEGIN IMMEDIATE and reads its authoritative transition time.
    prelock_finish = 200.0
    committed_time = 201.0 if clock_advances else 200.0
    monkeypatch.setattr(queue, "_now", lambda: committed_time)
    response = queue._store_status(
        identifier,
        status=terminal,
        stage="Ready" if terminal == "succeeded" else "Assembly failed",
        progress=100 if terminal == "succeeded" else 0,
        finished_at=prelock_finish,
    )
    assert response is not None
    with queue.connection() as db:
        raw, sql_updated = db.execute(
            "SELECT data,updated FROM records WHERE id=? AND kind=?",
            (identifier, "video_assembly_job"),
        ).fetchone()
    persisted = json.loads(raw)
    assert persisted["status"] == terminal
    assert response["updated_at"] == persisted["updated_at"] == sql_updated == committed_time
    assert response["finished_at"] == persisted["finished_at"] == committed_time, (
        "Terminal finished_at must reflect the same serialized transition as "
        "API updated_at and SQLite history; a pre-lock clock read is stale."
    )
