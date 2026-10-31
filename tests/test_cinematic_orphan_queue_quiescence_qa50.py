"""QA50: prevent the QA49 orphan-media inventory from hiding active master encoders.

Synthetic SQLite records only; no owner media, credentials, cloud services or
actual worker processes. An active queue row is a conservative uncertainty
signal, NOT proof that FFmpeg is running or that an MP4 is safe to delete.
"""
from __future__ import annotations

from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sqlite3

TOOL = Path(__file__).resolve().parents[1] / "tools" / "cinematic_orphan_media_audit_qa49.py"
spec = importlib.util.spec_from_file_location("cinematic_orphan_media_audit_qa49", TOOL)
assert spec and spec.loader
audit_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_module)


def _workspace(tmp_path: Path) -> Path:
    (tmp_path / "video-assets").mkdir()
    db = tmp_path / "studio.sqlite"
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("CREATE TABLE records (id TEXT PRIMARY KEY, kind TEXT, data TEXT, updated REAL)")
        conn.commit()
    return db


def _record(db: Path, index: int, kind: str, value: object) -> None:
    raw = value if isinstance(value, str) else json.dumps(value)
    with closing(sqlite3.connect(db)) as conn:
        conn.execute(
            "INSERT INTO records (id,kind,data,updated) VALUES (?,?,?,?)",
            (f"{index:032x}", kind, raw, float(index)),
        )
        conn.commit()


def test_running_master_queue_row_prevents_false_quiescence(tmp_path: Path) -> None:
    db = _workspace(tmp_path)
    _record(db, 1, "video_assembly_job", {
        "status": "running", "project_id": "a" * 32,
        "project_revision": 3, "ffmpeg_path": "ffmpeg",
        "prompt": "PRIVATE_SCRIPT_QA50_CANARY",
    })
    # A real encoder may have created this UUID-named file before the
    # video_master record exists. Do not infer orphan ownership from it.
    (tmp_path / "video-assets" / ("b" * 32 + ".mp4")).write_bytes(b"partial")
    result = audit_module.audit(tmp_path, db)
    assert result["master_assembly_jobs_pending_or_running"] == 1
    assert result["candidate_inventory_not_quiescent"] is True
    assert result["candidate_untracked_mp4_files"] == 1
    assert result["safe_to_delete_automatically"] is False
    serialized = json.dumps(result)
    assert "PRIVATE_SCRIPT_QA50_CANARY" not in serialized
    assert "a" * 32 not in serialized and "b" * 32 not in serialized
    assert str(tmp_path) not in serialized


def test_queued_master_may_start_during_inventory(tmp_path: Path) -> None:
    db = _workspace(tmp_path)
    _record(db, 1, "video_assembly_job", {"status": "queued"})
    result = audit_module.audit(tmp_path, db)
    assert result["master_assembly_jobs_pending_or_running"] == 1
    assert result["candidate_inventory_not_quiescent"] is True
    assert result["safe_to_delete_automatically"] is False


def test_malformed_and_unknown_master_queue_rows_do_not_hide_uncertainty(tmp_path: Path) -> None:
    db = _workspace(tmp_path)
    _record(db, 1, "video_assembly_job", "{not json")
    _record(db, 2, "video_assembly_job", ["unexpected", "array"])
    _record(db, 3, "video_assembly_job", {"status": ["running"]})
    result = audit_module.audit(tmp_path, db)
    assert result["malformed_record_count"] == 2
    assert result["invalid_master_assembly_status_rows"] == 1
    assert result["candidate_inventory_not_quiescent"] is True
    assert result["safe_to_delete_automatically"] is False


def test_terminal_master_queue_row_is_not_mistaken_for_active_encoder(tmp_path: Path) -> None:
    db = _workspace(tmp_path)
    _record(db, 1, "video_assembly_job", {"status": "succeeded", "asset_id": "c" * 32})
    _record(db, 2, "video_master", {"status": "ready", "asset_id": "c" * 32})
    (tmp_path / "video-assets" / ("c" * 32 + ".mp4")).write_bytes(b"tracked")
    result = audit_module.audit(tmp_path, db)
    assert result["master_assembly_jobs_pending_or_running"] == 0
    assert result["invalid_master_assembly_status_rows"] == 0
    assert result["candidate_inventory_not_quiescent"] is False
    assert result["candidate_untracked_mp4_files"] == 0
    # A quiet DB is not process-level fencing or permission to delete media.
    assert result["safe_to_delete_automatically"] is False
