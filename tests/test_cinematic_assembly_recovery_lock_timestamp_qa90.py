"""QA90: startup recovery must timestamp after acquiring its SQLite write lock.

Real SQLite interleaving with synthetic queue records only. No FFmpeg, inference,
owner media, owner-PC restart or physical mobile playback.
Frozen parent: QA89 #185 at 294365a6d1ed8fe21f4d7436b7a085ec0570a2f4.
"""
from __future__ import annotations

from contextlib import contextmanager
import importlib
import json
import sqlite3

import pytest


@pytest.mark.parametrize("writer_interleaves", [False, True], ids=["stable-control", "writer-before-recovery-lock"])
def test_recovery_timestamp_is_serialized(monkeypatch, tmp_path, writer_interleaves):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    queue = importlib.import_module("app.video.cinematic_assembly_jobs")
    identifier, project_id = "a" * 32, "b" * 32
    payload = {
        "project_id": project_id,
        "project_revision": 3,
        "ffmpeg_path": "ffmpeg",
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

    original_connection = queue.connection
    writer_committed = False

    @contextmanager
    def interleaved_connection():
        nonlocal writer_committed
        with original_connection() as db:
            if writer_interleaves and not writer_committed:
                # An independent writer commits after recovery begins but
                # before it acquires BEGIN IMMEDIATE.
                revised = {**payload, "updated_at": 250.0}
                with sqlite3.connect(tmp_path / "studio.sqlite") as writer:
                    writer.execute(
                        "UPDATE records SET data=?,updated=? WHERE id=?",
                        (json.dumps(revised), 250.0, identifier),
                    )
                writer_committed = True
            yield db

    monkeypatch.setattr(queue, "connection", interleaved_connection)
    monkeypatch.setattr(queue, "_now", lambda: 300.0 if writer_committed else 200.0)
    # No worker threads: this test is exclusively about persisted recovery.
    monkeypatch.setattr(queue, "_dispatch", lambda: None)

    outcome = queue.recover_assembly_queue()
    assert outcome == {"interrupted": 1}
    expected = 300.0 if writer_interleaves else 200.0
    with original_connection() as db:
        raw, sql_updated = db.execute(
            "SELECT data,updated FROM records WHERE id=? AND kind=?",
            (identifier, "video_assembly_job"),
        ).fetchone()
    persisted = json.loads(raw)
    assert persisted["status"] == "failed"
    assert persisted["stage"] == "Interrupted"
    assert persisted["finished_at"] == persisted["updated_at"] == sql_updated == expected, (
        "Startup recovery must not regress durable history after an intervening "
        "writer commits before the recovery transaction lock."
    )
