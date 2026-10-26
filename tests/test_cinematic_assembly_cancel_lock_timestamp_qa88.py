"""QA88: cancellation must timestamp the committed state, not a stale pre-lock instant.

Synthetic SQLite interleaving only; no FFmpeg, AI inference, owner media or phone.
Frozen parent QA87 #181 at 56e247a233dfe7f745618d5dbe484177fc9c05ce.
"""
from __future__ import annotations

from contextlib import contextmanager
import importlib
import json
import sqlite3

import pytest


@pytest.mark.parametrize("concurrent_update", [False, True], ids=["stable-control", "writer-before-lock"])
def test_cancel_timestamps_follow_serialized_transition(monkeypatch, tmp_path, concurrent_update):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    queue = importlib.import_module("app.video.cinematic_assembly_jobs")
    project_id, identifier = "b" * 32, "a" * 32
    payload = {
        "project_id": project_id,
        "project_revision": 3,
        "ffmpeg_path": "ffmpeg",
        "status": "queued",
        "stage": "Queued",
        "created_at": 100.0,
        "updated_at": 100.0,
        "progress": 0,
    }
    with queue.connection() as db:
        db.execute(
            "INSERT INTO records(id,kind,data,updated) VALUES(?,?,?,?)",
            (identifier, "video_assembly_job", json.dumps(payload), 100.0),
        )

    original_connection = queue.connection
    writer_committed = False

    @contextmanager
    def interleaved_connection():
        nonlocal writer_committed
        with original_connection() as db:
            if concurrent_update and not writer_committed:
                # Another legitimate SQLite writer wins the interval between
                # cancellation's pre-lock clock read and its BEGIN IMMEDIATE.
                # Use an independent connection so this is an actual commit.
                revised = {**payload, "updated_at": 250.0}
                with sqlite3.connect(tmp_path / "studio.sqlite") as writer:
                    writer.execute(
                        "UPDATE records SET data=?,updated=? WHERE id=?",
                        (json.dumps(revised), 250.0, identifier),
                    )
                writer_committed = True
            yield db

    monkeypatch.setattr(queue, "connection", interleaved_connection)
    # A clock read before the intervening writer is stale (200); a clock read
    # after entering the serialized transition is 300.
    monkeypatch.setattr(queue, "_now", lambda: 300.0 if writer_committed else 200.0)

    cancelled = queue.cancel_queued_master_assembly(project_id, identifier)
    assert cancelled["status"] == "cancelled"
    expected = 300.0 if concurrent_update else 200.0
    assert cancelled["updated_at"] == expected, (
        "Cancellation must not regress the durable history timestamp after "
        "another writer commits before the cancellation lock"
    )
    assert cancelled["finished_at"] == expected

    with original_connection() as db:
        raw, updated = db.execute(
            "SELECT data,updated FROM records WHERE id=? AND kind=?",
            (identifier, "video_assembly_job"),
        ).fetchone()
    persisted = json.loads(raw)
    assert persisted["status"] == "cancelled"
    assert persisted["updated_at"] == updated == expected
