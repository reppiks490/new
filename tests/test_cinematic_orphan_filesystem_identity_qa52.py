"""QA52: offline MP4 inventory must fail closed on unsafe directory entries.

Uses real temporary SQLite and synthetic filesystem entries, no owner media.
The inspector is read-only and must not follow symlinks or count hardlinked
external files as ordinary, uniquely-owned orphan candidates.
"""
from __future__ import annotations

from contextlib import closing
import importlib.util
import json
import os
from pathlib import Path
import sqlite3

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "cinematic_orphan_media_audit_qa49.py"
spec = importlib.util.spec_from_file_location("cinematic_orphan_media_audit_qa49", TOOL)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

NAME = "a" * 32 + ".mp4"


def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "studio"
    (workspace / "video-assets").mkdir(parents=True)
    db_path = workspace / "studio.sqlite"
    with closing(sqlite3.connect(db_path)) as db:
        db.execute("CREATE TABLE records (id TEXT PRIMARY KEY, kind TEXT, data TEXT, updated REAL)")
        db.commit()
    return workspace, db_path


def _assert_unsafe(result: dict, expected_unsafe: int = 1) -> None:
    assert result["unsafe_mp4_entries_skipped"] == expected_unsafe
    assert result["candidate_untracked_mp4_files"] == 0
    assert result["candidate_untracked_bytes"] == 0
    assert result["candidate_inventory_not_quiescent"] is True
    assert result["safe_to_delete_automatically"] is False
    assert not any("path" in key or "name" in key or "prompt" in key for key in result)


def test_external_symlink_is_unsafe_and_blocks_quiescence(tmp_path: Path) -> None:
    workspace, db = _workspace(tmp_path)
    private = tmp_path / "PRIVATE_QA52_OWNER_MEDIA.mp4"
    private.write_bytes(b"private-not-opened")
    target = workspace / "video-assets" / NAME
    try:
        target.symlink_to(private)
    except (NotImplementedError, OSError):
        pytest.skip("symlinks unavailable")
    before = private.read_bytes()
    result = module.audit(workspace, db)
    _assert_unsafe(result)
    assert private.read_bytes() == before
    assert "PRIVATE_QA52_OWNER_MEDIA" not in json.dumps(result)


def test_dangling_symlink_is_unsafe_and_blocks_quiescence(tmp_path: Path) -> None:
    workspace, db = _workspace(tmp_path)
    target = workspace / "video-assets" / NAME
    try:
        target.symlink_to(tmp_path / "MISSING_PRIVATE_QA52.mp4")
    except (NotImplementedError, OSError):
        pytest.skip("symlinks unavailable")
    _assert_unsafe(module.audit(workspace, db))


def test_external_hardlink_is_not_counted_as_private_orphan(tmp_path: Path) -> None:
    workspace, db = _workspace(tmp_path)
    private = tmp_path / "PRIVATE_QA52_OWNER_MEDIA.mp4"
    private.write_bytes(b"private-hardlinked-bytes")
    target = workspace / "video-assets" / NAME
    try:
        os.link(private, target)
    except OSError:
        pytest.skip("hardlinks unavailable")
    assert private.stat().st_nlink >= 2
    _assert_unsafe(module.audit(workspace, db))
    assert private.read_bytes() == b"private-hardlinked-bytes"


def test_directory_named_mp4_is_unsafe_and_blocks_quiescence(tmp_path: Path) -> None:
    workspace, db = _workspace(tmp_path)
    (workspace / "video-assets" / NAME).mkdir()
    _assert_unsafe(module.audit(workspace, db))


def test_unique_regular_candidate_remains_visible_without_deletion(tmp_path: Path) -> None:
    workspace, db = _workspace(tmp_path)
    (workspace / "video-assets" / NAME).write_bytes(b"synthetic")
    result = module.audit(workspace, db)
    assert result["candidate_untracked_mp4_files"] == 1
    assert result["candidate_untracked_bytes"] == len(b"synthetic")
    assert result["unsafe_mp4_entries_skipped"] == 0
    assert result["candidate_inventory_not_quiescent"] is False
    assert result["safe_to_delete_automatically"] is False
