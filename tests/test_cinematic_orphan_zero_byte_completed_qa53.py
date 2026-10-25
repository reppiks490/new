"""QA53: completed zero-byte MP4s cannot be treated as healthy inventory.

Real temporary SQLite persistence and synthetic empty/nonempty files; no owner
media, model inference, FFmpeg invocation or automatic cleanup.
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
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def _workspace(tmp_path: Path, kind: str, status: str, *, file_bytes: bytes) -> tuple[Path, Path]:
    assets = tmp_path / "video-assets"
    assets.mkdir()
    identifier = "d" * 32
    (assets / f"{identifier}.mp4").write_bytes(file_bytes)
    database = tmp_path / "studio.sqlite"
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("CREATE TABLE records (id TEXT PRIMARY KEY, kind TEXT, data TEXT, updated REAL)")
        conn.execute(
            "INSERT INTO records(id,kind,data,updated) VALUES (?,?,?,?)",
            ("e" * 32, kind, json.dumps({
                "status": status, "asset_id": identifier,
                "prompt": "PRIVATE_QA53_NOT_FOR_OUTPUT"
            }), 1.0),
        )
        conn.commit()
    return tmp_path, database


@pytest.mark.parametrize(("kind", "status"), [
    ("video_master", "ready"),
    ("video_job", "succeeded"),
])
def test_completed_zero_byte_mp4_blocks_false_quiescence(
    tmp_path: Path, kind: str, status: str
) -> None:
    workspace, database = _workspace(tmp_path, kind, status, file_bytes=b"")
    result = module.audit(workspace, database)
    assert result["missing_completed_mp4_ids"] == 0
    assert result["zero_byte_completed_mp4_files"] == 1
    assert result["candidate_inventory_not_quiescent"] is True
    assert result["safe_to_delete_automatically"] is False
    assert "PRIVATE_QA53_NOT_FOR_OUTPUT" not in json.dumps(result)
    assert not any("path" in key or "prompt" in key for key in result)


def test_nonempty_completed_media_does_not_trigger_zero_byte_gate(tmp_path: Path) -> None:
    workspace, database = _workspace(
        tmp_path, "video_master", "ready", file_bytes=b"synthetic nonempty"
    )
    result = module.audit(workspace, database)
    assert result["zero_byte_completed_mp4_files"] == 0
    assert result["candidate_inventory_not_quiescent"] is False
    assert result["safe_to_delete_automatically"] is False


def test_zero_byte_untracked_candidate_remains_only_candidate(tmp_path: Path) -> None:
    (tmp_path / "video-assets").mkdir()
    (tmp_path / "video-assets" / ("d" * 32 + ".mp4")).write_bytes(b"")
    database = tmp_path / "studio.sqlite"
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("CREATE TABLE records (id TEXT PRIMARY KEY, kind TEXT, data TEXT, updated REAL)")
        conn.commit()
    result = module.audit(tmp_path, database)
    assert result["zero_byte_completed_mp4_files"] == 0
    assert result["candidate_untracked_mp4_files"] == 1
    assert result["candidate_small_files_under_128_bytes"] == 1
    assert result["candidate_inventory_not_quiescent"] is False
