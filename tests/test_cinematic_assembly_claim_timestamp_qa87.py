"""QA87: claiming a queued cinematic master must persist one consistent timestamp.

Synthetic SQLite records only. No FFmpeg, model inference, owner footage or mobile device.
Frozen parent: QA86 PR #180 at 66e25a8d150bdf958371cc634932e0fd2946235a.
"""
from __future__ import annotations

import importlib
import json


def _insert(queue, identifier: str, status: str, updated: float = 100.0):
    payload = {
        "project_id": "b" * 32,
        "project_revision": 3,
        "ffmpeg_path": "ffmpeg",
        "status": status,
        "stage": "Queued" if status == "queued" else "Assembling",
        "created_at": 100.0,
        "updated_at": updated,
        "progress": 0 if status == "queued" else None,
    }
    with queue.connection() as db:
        db.execute(
            "INSERT INTO records(id,kind,data,updated) VALUES(?,?,?,?)",
            (identifier, "video_assembly_job", json.dumps(payload), updated),
        )


def test_claim_uses_one_timestamp_for_started_at_updated_at_and_sqlite(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    queue = importlib.import_module("app.video.cinematic_assembly_jobs")
    identifier = "a" * 32
    _insert(queue, identifier, "queued")

    clock = iter([200.0, 201.0, 202.0])
    monkeypatch.setattr(queue, "_now", lambda: next(clock))
    claimed = queue._claim_next()

    assert claimed is not None and claimed["id"] == identifier
    assert claimed["status"] == "running"
    assert claimed["started_at"] == 200.0
    assert claimed["updated_at"] == claimed["started_at"], (
        "Claim response must use the same instant for started_at and updated_at"
    )

    persisted = queue.get_master_assembly_job("b" * 32, identifier)
    with queue.connection() as db:
        db_updated = db.execute(
            "SELECT updated FROM records WHERE id=? AND kind=?",
            (identifier, "video_assembly_job"),
        ).fetchone()[0]
    assert persisted["updated_at"] == claimed["updated_at"]
    assert db_updated == claimed["updated_at"], (
        "SQLite history ordering must agree with the API-visible claim time"
    )


def test_claim_refuses_new_work_when_another_job_is_running(monkeypatch, tmp_path):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    queue = importlib.import_module("app.video.cinematic_assembly_jobs")
    _insert(queue, "c" * 32, "running")
    _insert(queue, "d" * 32, "queued")

    assert queue._claim_next() is None
    with queue.connection() as db:
        status = db.execute(
            "SELECT json_extract(data,'$.status') FROM records WHERE id=?",
            ("d" * 32,),
        ).fetchone()[0]
    assert status == "queued"
