"""QA51: conservative offline orphan inventory when video record integrity is uncertain.

Actual temporary SQLite databases, synthetic records and candidate bytes only.
This tests a diagnostic contract, not real process quiescence or safe deletion.
"""
from __future__ import annotations

from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "cinematic_orphan_media_audit_qa49.py"
spec = importlib.util.spec_from_file_location("cinematic_orphan_media_audit_qa49", TOOL)
assert spec and spec.loader
audit_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_module)


def _db(tmp_path: Path) -> Path:
    (tmp_path / "video-assets").mkdir()
    database = tmp_path / "studio.sqlite"
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("CREATE TABLE records (id TEXT PRIMARY KEY, kind TEXT, data TEXT, updated REAL)")
        conn.commit()
    return database


def _insert(database: Path, n: int, kind: str, payload: dict) -> None:
    with closing(sqlite3.connect(database)) as conn:
        conn.execute(
            "INSERT INTO records(id,kind,data,updated) VALUES (?,?,?,?)",
            (f"{n:032x}", kind, json.dumps(payload), float(n)),
        )
        conn.commit()


@pytest.mark.parametrize("status", ["generating", ["running"]])
def test_invalid_video_generation_status_blocks_false_quiescence(tmp_path: Path, status: object) -> None:
    db = _db(tmp_path)
    _insert(db, 1, "video_job", {"status": status, "prompt": "PRIVATE_QA51_PROMPT"})
    (tmp_path / "video-assets" / ("b" * 32 + ".mp4")).write_bytes(b"candidate")
    result = audit_module.audit(tmp_path, db)
    assert result["active_video_jobs"] == 0
    assert result["invalid_video_job_status_rows"] == 1
    assert result["candidate_untracked_mp4_files"] == 1
    assert result["candidate_inventory_not_quiescent"] is True
    assert result["safe_to_delete_automatically"] is False
    assert "PRIVATE_QA51_PROMPT" not in json.dumps(result)


@pytest.mark.parametrize("status", ["failed", {"unexpected": "ready"}])
def test_invalid_video_master_status_blocks_false_quiescence(tmp_path: Path, status: object) -> None:
    db = _db(tmp_path)
    _insert(db, 1, "video_master", {"status": status, "asset_id": "a" * 32})
    result = audit_module.audit(tmp_path, db)
    assert result["invalid_video_master_status_rows"] == 1
    assert result["candidate_inventory_not_quiescent"] is True
    assert result["safe_to_delete_automatically"] is False


def test_successful_job_and_ready_master_missing_asset_references(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _insert(db, 1, "video_job", {"status": "succeeded"})
    _insert(db, 2, "video_master", {"status": "ready"})
    result = audit_module.audit(tmp_path, db)
    assert result["invalid_completed_asset_reference_rows"] == 2
    assert result["candidate_inventory_not_quiescent"] is True
    assert result["safe_to_delete_automatically"] is False


def test_invalid_asset_reference_cannot_imply_quiescent_inventory(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _insert(db, 1, "video_master", {
        "status": "ready", "asset_id": "../PRIVATE_OWNER_PATH_QA51"
    })
    result = audit_module.audit(tmp_path, db)
    assert result["invalid_asset_id_count"] == 1
    assert result["candidate_inventory_not_quiescent"] is True
    assert "PRIVATE_OWNER_PATH_QA51" not in json.dumps(result)
    assert result["safe_to_delete_automatically"] is False


def test_valid_terminal_records_preserve_quiet_database_semantics(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _insert(db, 1, "video_job", {"status": "succeeded", "asset_id": "a" * 32})
    _insert(db, 2, "video_master", {"status": "ready", "asset_id": "b" * 32})
    _insert(db, 3, "video_job", {"status": "failed"})
    result = audit_module.audit(tmp_path, db)
    assert result["invalid_video_job_status_rows"] == 0
    assert result["invalid_video_master_status_rows"] == 0
    assert result["invalid_completed_asset_reference_rows"] == 0
    assert result["candidate_inventory_not_quiescent"] is False
    assert result["missing_completed_mp4_ids"] == 2
    assert result["safe_to_delete_automatically"] is False


def test_valid_active_video_job_is_counted_not_mislabeled_invalid(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _insert(db, 1, "video_job", {"status": "running"})
    _insert(db, 2, "video_assembly_job", {"status": "queued"})
    result = audit_module.audit(tmp_path, db)
    assert result["active_video_jobs"] == 1
    assert result["master_assembly_jobs_pending_or_running"] == 1
    assert result["invalid_video_job_status_rows"] == 0
    assert result["candidate_inventory_not_quiescent"] is True
