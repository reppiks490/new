"""Real temporary SQLite tests; no FFmpeg, model inference or owner data."""
from __future__ import annotations

import importlib.util
from contextlib import contextmanager, closing
import json
from pathlib import Path
import sqlite3

import pytest


SOURCE = Path(__file__).resolve().parents[1] / "tools" / "cinematic_queue_health_qa43.py"
spec = importlib.util.spec_from_file_location("cinematic_queue_health_qa43", SOURCE)
health = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(health)


@contextmanager
def _database(path):
    db = sqlite3.connect(path)
    try:
        db.execute("CREATE TABLE records (id TEXT PRIMARY KEY, kind TEXT, data TEXT, updated REAL)")
        with db:
            yield db
    finally:
        db.close()


def _put(db, identifier, status, updated, *, kind="video_assembly_job", raw=None):
    private = "OWNER_PRIVATE_SCREENPLAY_DO_NOT_EXPOSE"
    data = raw if raw is not None else json.dumps({
        "status": status, "master_prompt": private, "ffmpeg_path": private,
        "project_id": private, "error": private,
    })
    db.execute("INSERT INTO records VALUES (?,?,?,?)", (identifier, kind, data, updated))


def test_counts_ages_privacy_and_no_row_mutation(tmp_path):
    path = tmp_path / "studio.sqlite"
    with _database(path) as db:
        _put(db, "1", "queued", 100)
        _put(db, "2", "running", 110)
        _put(db, "3", "failed", 90)
        _put(db, "4", "succeeded", 80)
        _put(db, "5", "cancelled", 70)
        _put(db, "6", "queued", 120, kind="video_job")
    with closing(sqlite3.connect(path)) as db:
        before = db.execute("SELECT * FROM records ORDER BY id").fetchall()
    report = health.inspect_queue(path, now=150)
    assert report["counts"] == {
        "queued": 1, "running": 1, "failed": 1,
        "succeeded": 1, "cancelled": 1, "unknown": 0,
    }
    assert report["outstanding"] == 2
    assert report["oldest_queued_age_seconds"] == 50
    assert report["oldest_running_age_seconds"] == 40
    assert report["warnings"] == []
    assert report["worker_liveness_verified"] is False
    assert "OWNER_PRIVATE" not in json.dumps(report)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT * FROM records ORDER BY id").fetchall() == before


def test_multiple_running_capacity_and_unknown_status(tmp_path):
    path = tmp_path / "studio.sqlite"
    with _database(path) as db:
        _put(db, "1", "running", 10)
        _put(db, "2", "running", 20)
        _put(db, "3", "queued", 30)
        _put(db, "4", "unknown-private-state", 40)
        _put(db, "5", None, 50, raw="{malformed json")
    report = health.inspect_queue(path, now=100)
    assert report["outstanding"] == 3
    assert report["counts"]["unknown"] == 2
    assert report["warnings"] == [
        "multiple_running_records", "unrecognized_status_records"
    ]


def test_capacity_warning_without_false_orphan_claim(tmp_path, monkeypatch):
    path = tmp_path / "studio.sqlite"
    with _database(path) as db:
        for i in range(4):
            _put(db, str(i), "queued", i)
    monkeypatch.setattr(health, "_CAPACITY", 4)
    report = health.inspect_queue(path, now=100)
    assert report["warnings"] == ["queue_at_or_over_capacity"]
    assert "orphan" not in json.dumps(report).lower()


def test_invalid_and_future_timestamps_do_not_create_negative_ages(tmp_path):
    path = tmp_path / "studio.sqlite"
    with _database(path) as db:
        _put(db, "1", "queued", None)
        _put(db, "2", "running", 9999)
        _put(db, "3", "queued", 10)
    report = health.inspect_queue(path, now=100)
    assert report["oldest_queued_age_seconds"] == 90
    assert report["oldest_running_age_seconds"] is None
    assert report["warnings"] == ["invalid_active_timestamps", "future_active_timestamps"]


def test_missing_db_and_schema_fail_closed_without_creating_files(tmp_path, capsys):
    path = tmp_path / "OWNER_PRIVATE_SCREENPLAY_DO_NOT_EXPOSE.sqlite"
    assert health.main(["--db", str(path)]) == 2
    assert not path.exists()
    captured = capsys.readouterr()
    assert "OWNER_PRIVATE" not in captured.out + captured.err
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE unrelated (value TEXT)")
        db.commit()
    with pytest.raises(health.QueueHealthError):
        health.inspect_queue(path)


def test_wal_committed_queue_row_visible_without_recovery_or_dispatch(tmp_path):
    path = tmp_path / "studio.sqlite"
    with _database(path) as db:
        pass
    with closing(sqlite3.connect(path)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        _put(writer, "queued-committed", "queued", 50)
        writer.commit()
        assert health.inspect_queue(path, now=100)["counts"]["queued"] == 1
        assert writer.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 1


def test_cli_outputs_only_neutral_json(tmp_path, capsys):
    path = tmp_path / "studio.sqlite"
    with _database(path) as db:
        _put(db, "1", "failed", 50)
    assert health.main(["--db", str(path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["counts"]["failed"] == 1
    assert "OWNER_PRIVATE" not in json.dumps(report)
