"""QA44: one malformed persisted master row must not poison healthy queue work.

Synthetic SQLite rows only. This does not simulate a damaged SQLite database
page, a real FFmpeg process, an owner workspace, or a production incident.
Strict expected-red contracts run only in the dedicated QA44 workflow.
"""
from __future__ import annotations

import json
import os
import sqlite3

import pytest

from app.studio.storage import connection
from app.video import cinematic_assembly_jobs as queue


GOOD_ID = "a" * 32
BAD_ID = "b" * 32
PROJECT_ID = "c" * 32
STRICT = os.getenv("CINEMATIC_STRICT_MALFORMED_QUEUE_QA44") == "1"


class HoldingPool:
    def __init__(self):
        self.submissions = []

    def submit(self, fn, *args, **kwargs):
        self.submissions.append((fn, args, kwargs))
        return object()


def _seed_queue(monkeypatch, tmp_path, *, malformed: bool):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    healthy = {
        "project_id": PROJECT_ID,
        "project_revision": 1,
        "ffmpeg_path": "ffmpeg",
        "status": "queued",
        "stage": "Queued",
        "created_at": 100.0,
        "updated_at": 100.0,
        "progress": 0,
    }
    with connection() as db:
        db.execute(
            "INSERT INTO records(id,kind,data,updated) VALUES(?,?,?,?)",
            (GOOD_ID, "video_assembly_job", json.dumps(healthy), 100.0),
        )
        if malformed:
            # Deliberately invalid JSON text, not an invalid SQLite page.
            db.execute(
                "INSERT INTO records(id,kind,data,updated) VALUES(?,?,?,?)",
                (BAD_ID, "video_assembly_job", '{"status": "running", BROKEN', 50.0),
            )


def _assert_malformed_preserved():
    with connection() as db:
        row = db.execute(
            "SELECT data FROM records WHERE id=? AND kind=?",
            (BAD_ID, "video_assembly_job"),
        ).fetchone()
    assert row is not None
    assert row[0] == '{"status": "running", BROKEN'


def test_control_valid_sqlite_queue_claims_healthy_job(monkeypatch, tmp_path):
    _seed_queue(monkeypatch, tmp_path, malformed=False)
    claimed = queue._claim_next()
    assert claimed is not None
    assert claimed["id"] == GOOD_ID
    assert claimed["status"] == "running"


@pytest.mark.skipif(not STRICT, reason="strict QA44 expected-red queue isolation contract")
def test_malformed_row_cannot_block_unrelated_queued_master(monkeypatch, tmp_path):
    _seed_queue(monkeypatch, tmp_path, malformed=True)
    try:
        claimed = queue._claim_next()
    except sqlite3.OperationalError:
        pytest.fail("A malformed persisted master row blocked a healthy queued job")
    assert claimed is not None and claimed["id"] == GOOD_ID
    assert claimed["status"] == "running"
    _assert_malformed_preserved()


@pytest.mark.skipif(not STRICT, reason="strict QA44 expected-red startup contract")
def test_malformed_row_cannot_block_safe_startup_replay(monkeypatch, tmp_path):
    _seed_queue(monkeypatch, tmp_path, malformed=True)
    pool = HoldingPool()
    monkeypatch.setattr(queue, "assembly_pool", pool)
    try:
        result = queue.recover_assembly_queue()
    except sqlite3.OperationalError:
        pytest.fail("A malformed persisted master row blocked startup queue recovery")
    assert result["interrupted"] == 0
    assert len(pool.submissions) == 1
    _assert_malformed_preserved()
