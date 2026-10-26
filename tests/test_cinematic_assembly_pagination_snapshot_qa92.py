"""QA92: assembly history count and page must share one SQLite snapshot.

A real second SQLite connection commits between the COUNT and page SELECT.
The records are synthetic; no FFmpeg, inference, owner media or phone involved.
Frozen parent: QA91 #188 at 35ae3d66f1af3a3ca8468b27eeeab59d97745aea.
"""
from __future__ import annotations

from contextlib import contextmanager
import importlib
import json
import sqlite3

import pytest


@pytest.mark.parametrize("interleave", [False, True], ids=["stable-control", "concurrent-writer"])
def test_assembly_history_count_and_page_share_snapshot(monkeypatch, tmp_path, interleave):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    queue = importlib.import_module("app.video.cinematic_assembly_jobs")
    project_id = "b" * 32
    original_id, new_id = "a" * 32, "c" * 32

    def payload(updated):
        return {
            "project_id": project_id,
            "project_revision": 1,
            "status": "succeeded",
            "stage": "Ready",
            "created_at": updated,
            "updated_at": updated,
        }

    with queue.connection() as db:
        db.execute(
            "INSERT INTO records(id,kind,data,updated) VALUES(?,?,?,?)",
            (original_id, "video_assembly_job", json.dumps(payload(100.0)), 100.0),
        )

    original_connection = queue.connection
    writer_committed = False

    @contextmanager
    def interleaved_connection():
        nonlocal writer_committed
        with original_connection() as db:
            class InterleavedDB:
                def execute(self, sql, *args):
                    nonlocal writer_committed
                    cursor = db.execute(sql, *args)
                    if interleave and not writer_committed and sql.startswith(
                        "SELECT COUNT(*) FROM records WHERE kind=?"
                    ):
                        # The count statement has already begun its read.
                        # WAL permits this independent writer to commit now.
                        with sqlite3.connect(tmp_path / "studio.sqlite") as writer:
                            writer.execute(
                                "INSERT INTO records(id,kind,data,updated) VALUES(?,?,?,?)",
                                (new_id, "video_assembly_job", json.dumps(payload(300.0)), 300.0),
                            )
                        writer_committed = True
                    return cursor

            yield InterleavedDB()

    monkeypatch.setattr(queue, "connection", interleaved_connection)
    page = queue.list_master_assembly_jobs(project_id, limit=2, offset=0)
    assert page["total"] == 1
    assert page["has_more"] is False
    assert [job["id"] for job in page["jobs"]] == [original_id], (
        "COUNT and page must come from one read snapshot; otherwise a concurrent "
        "insert makes mobile history internally inconsistent"
    )

    with original_connection() as db:
        actual_count = db.execute(
            "SELECT COUNT(*) FROM records WHERE kind=?",
            ("video_assembly_job",),
        ).fetchone()[0]
    assert actual_count == (2 if interleave else 1)
