"""QA91: enqueue timestamps must be captured after the SQLite write lock.

Real SQLite interleaving with synthetic queue records; no FFmpeg, inference,
owner media, owner-PC rendering or physical mobile playback.
Frozen parent: QA90 #187 d81d3b15706cefcd450d9597d25a9d51618779f3.
"""
from __future__ import annotations

from contextlib import contextmanager
import importlib
import json
import sqlite3
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize(
    "writer_interleaves", [False, True],
    ids=["stable-control", "writer-before-enqueue-lock"],
)
def test_enqueue_timestamp_follows_serialized_admission(
    monkeypatch, tmp_path, writer_interleaves
):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    queue = importlib.import_module("app.video.cinematic_assembly_jobs")
    project_id, other_project = "b" * 32, "c" * 32
    other_id = "a" * 32
    prior = {
        "project_id": other_project,
        "project_revision": 2,
        "ffmpeg_path": "ffmpeg",
        "status": "succeeded",
        "stage": "Ready",
        "created_at": 100.0,
        "updated_at": 100.0,
        "progress": 100,
    }
    with queue.connection() as db:
        db.execute(
            "INSERT INTO records(id,kind,data,updated) VALUES(?,?,?,?)",
            (other_id, "video_assembly_job", json.dumps(prior), 100.0),
        )

    # Isolate admission metadata: no real rendering or worker thread.
    monkeypatch.setattr(queue, "get_project", lambda _: SimpleNamespace(revision=3))
    monkeypatch.setattr(queue, "enforce_film_duration", lambda _: None)
    monkeypatch.setattr(
        queue, "project_render_status", lambda _: {"ready_for_assembly": True}
    )
    monkeypatch.setattr(queue, "_dispatch", lambda: None)
    original_connection = queue.connection
    writer_committed = False

    @contextmanager
    def interleaved_connection():
        nonlocal writer_committed
        with original_connection() as db:
            if writer_interleaves and not writer_committed:
                # An independent SQLite writer commits between enqueue's
                # pre-lock clock read and its BEGIN IMMEDIATE transaction.
                revised = {**prior, "updated_at": 250.0}
                with sqlite3.connect(tmp_path / "studio.sqlite") as writer:
                    writer.execute(
                        "UPDATE records SET data=?,updated=? WHERE id=?",
                        (json.dumps(revised), 250.0, other_id),
                    )
                writer_committed = True
            yield db

    monkeypatch.setattr(queue, "connection", interleaved_connection)
    monkeypatch.setattr(queue, "_now", lambda: 300.0 if writer_committed else 200.0)

    queued = queue.enqueue_master_assembly(
        project_id, SimpleNamespace(expected_revision=3, ffmpeg_path="ffmpeg")
    )
    assert queued["status"] == "queued"
    expected = 300.0 if writer_interleaves else 200.0
    assert queued["created_at"] == queued["updated_at"] == expected, (
        "A new queue entry must use the serialized admission instant, not "
        "a timestamp predating another committed writer"
    )

    with original_connection() as db:
        raw, sql_updated = db.execute(
            "SELECT data,updated FROM records WHERE id=? AND kind=?",
            (queued["id"], "video_assembly_job"),
        ).fetchone()
    persisted = json.loads(raw)
    assert persisted["status"] == "queued"
    assert persisted["created_at"] == persisted["updated_at"] == sql_updated == expected
