"""QA86: persisted assembly status timestamps must reflect terminal transitions.

SQLite-backed synthetic queue records only: no FFmpeg, media, GPU, cloud or owner data.
The frozen integration parent is PR #40 at 05c59556d64a808dcc3a8ca96fae5e572c9e446d.
"""
from __future__ import annotations

import importlib
import json

import pytest


@pytest.mark.parametrize("terminal", ["succeeded", "failed"])
def test_running_to_terminal_updates_public_and_persisted_timestamp(
    monkeypatch, tmp_path, terminal
):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    queue = importlib.import_module("app.video.cinematic_assembly_jobs")
    identifier = "a" * 32
    project_id = "b" * 32
    initial = {
        "project_id": project_id,
        "project_revision": 3,
        "status": "running",
        "stage": "Assembling",
        "updated_at": 100.0,
        "started_at": 100.0,
        "progress": None,
    }
    with queue.connection() as db:
        db.execute(
            "INSERT INTO records(id,kind,data,updated) VALUES(?,?,?,?)",
            (identifier, "video_assembly_job", json.dumps(initial), 100.0),
        )

    monkeypatch.setattr(queue, "_now", lambda: 200.0)
    outcome = queue._store_status(
        identifier,
        status=terminal,
        stage="Ready" if terminal == "succeeded" else "Assembly failed",
        finished_at=200.0,
    )
    assert outcome is not None
    assert outcome["status"] == terminal
    assert outcome["updated_at"] == 200.0, "Response timestamp must reflect transition"

    persisted = queue.get_master_assembly_job(project_id, identifier)
    assert persisted["updated_at"] == 200.0, "Polling must not return stale time"
    with queue.connection() as db:
        updated = db.execute(
            "SELECT updated FROM records WHERE id=? AND kind=?",
            (identifier, "video_assembly_job"),
        ).fetchone()[0]
    assert updated == 200.0, "SQLite sort time must agree with JSON time"
