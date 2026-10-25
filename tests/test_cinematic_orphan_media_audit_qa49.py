"""QA49 synthetic SQLite and genuine FFmpeg orphan-inventory acceptance."""
from __future__ import annotations

import hashlib
from contextlib import closing
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "cinematic_orphan_media_audit_qa49.py"
spec = importlib.util.spec_from_file_location("cinematic_orphan_media_audit_qa49", TOOL)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def setup(tmp_path: Path):
    media = tmp_path / "video-assets"
    media.mkdir()
    dbpath = tmp_path / "studio.sqlite"
    with closing(sqlite3.connect(dbpath)) as db:
        db.execute("CREATE TABLE records(id TEXT PRIMARY KEY,kind TEXT,data TEXT,updated REAL)")
        db.commit()
    return dbpath, media


def insert(dbpath: Path, kind: str, payload: object, n: int):
    with closing(sqlite3.connect(dbpath)) as db:
        db.execute("INSERT INTO records VALUES(?,?,?,?)", (
            f"{n:032x}", kind,
            payload if isinstance(payload, str) else json.dumps(payload), float(n),
        ))
        db.commit()


def test_inventory_does_not_truncate_history_and_reports_missing(tmp_path):
    db, media = setup(tmp_path)
    for i in range(125):
        identifier = f"{i + 1000:032x}"
        insert(db, "video_master", {"asset_id": identifier, "status": "ready"}, i + 1)
        if i < 124:
            (media / (identifier + ".mp4")).write_bytes(b"synthetic")
    result = mod.audit(tmp_path, db)
    assert result["tracked_mp4_ids"] == 125
    assert result["missing_completed_mp4_ids"] == 1
    assert result["candidate_untracked_mp4_files"] == 0
    assert result["safe_to_delete_automatically"] is False


def test_active_and_malformed_rows_do_not_block_audit(tmp_path):
    db, media = setup(tmp_path)
    insert(db, "video_job", {"status": "running"}, 1)
    insert(db, "video_job", "{not valid json", 2)
    insert(db, "video_master", {"status": "ready", "asset_id": "not-an-id"}, 3)
    insert(db, "video_job", {"status": "succeeded", "asset_id": "a" * 32}, 4)
    (media / ("b" * 32 + ".mp4")).write_bytes(b"partial")
    result = mod.audit(tmp_path, db)
    assert result["active_video_jobs"] == 1
    assert result["malformed_record_count"] == 1
    assert result["invalid_asset_id_count"] == 1
    assert result["missing_completed_mp4_ids"] == 1
    assert result["candidate_untracked_mp4_files"] == 1
    assert result["candidate_small_files_under_128_bytes"] == 1


def test_no_media_or_sqlite_mutation_and_no_path_or_private_text(tmp_path):
    db, media = setup(tmp_path)
    private = "PRIVATE_SCREENPLAY_NEVER_EXPOSE"
    insert(db, "video_job", {"status": "succeeded", "asset_id": "a" * 32,
                             "prompt": private}, 1)
    (media / ("a" * 32 + ".mp4")).write_bytes(b"known")
    orphan = media / ("b" * 32 + ".mp4")
    orphan.write_bytes(b"orphan")
    before_db = hashlib.sha256(db.read_bytes()).digest()
    before_media = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in media.iterdir()}
    report = mod.audit(tmp_path, db)
    serialized = json.dumps(report)
    assert private not in serialized
    assert str(tmp_path) not in serialized
    assert "a" * 32 not in serialized and "b" * 32 not in serialized
    assert hashlib.sha256(db.read_bytes()).digest() == before_db
    assert before_media == {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in media.iterdir()}


def test_skips_symlink_mp4_without_following_it(tmp_path):
    db, media = setup(tmp_path)
    outside = tmp_path.parent / (tmp_path.name + "-private")
    outside.write_bytes(b"private content")
    (media / ("a" * 32 + ".mp4")).symlink_to(outside)
    result = mod.audit(tmp_path, db)
    assert result["unsafe_mp4_entries_skipped"] == 1
    assert result["candidate_untracked_mp4_files"] == 0
    assert outside.read_bytes() == b"private content"


def test_rejects_symlink_media_directory_and_database(tmp_path):
    db, media = setup(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    media.rmdir()
    media.symlink_to(other, target_is_directory=True)
    with pytest.raises(ValueError):
        mod.audit(tmp_path, db)
    media.unlink()
    media.mkdir()
    db_link = tmp_path / "alias.sqlite"
    db_link.symlink_to(db)
    with pytest.raises(ValueError):
        mod.audit(tmp_path, db_link)


def test_wal_committed_rows_visible_read_only(tmp_path):
    db, media = setup(tmp_path)
    writer = sqlite3.connect(db)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("INSERT INTO records VALUES(?,?,?,?)", (
            "1" * 32, "video_job", json.dumps({"status": "running"}), 1,
        ))
        writer.commit()
        assert mod.audit(tmp_path, db)["active_video_jobs"] == 1
    finally:
        writer.close()


def test_real_synthetic_ffmpeg_mp4_and_truncated_untracked_candidate(tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        if os.getenv("CINEMATIC_REQUIRE_REAL_MEDIA") == "1":
            pytest.fail("Dedicated QA49 requires genuine local FFmpeg")
        pytest.skip("FFmpeg unavailable in ordinary Python CI")
    db, media = setup(tmp_path)
    tracked_id, untracked_id = "a" * 32, "b" * 32
    output = media / (tracked_id + ".mp4")
    subprocess.run([
        ffmpeg, "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=blue:s=64x64:r=24:d=1",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(output),
    ], check=True, capture_output=True, timeout=60)
    assert output.stat().st_size > 128
    insert(db, "video_master", {"status": "ready", "asset_id": tracked_id}, 1)
    (media / (untracked_id + ".mp4")).write_bytes(output.read_bytes()[:64])
    result = mod.audit(tmp_path, db)
    assert result["completed_mp4_ids"] == 1
    assert result["missing_completed_mp4_ids"] == 0
    assert result["candidate_untracked_mp4_files"] == 1
    assert result["candidate_small_files_under_128_bytes"] == 1
    assert result["candidate_untracked_bytes"] == 64
    # A truncated MP4 is a synthetic crash-like artifact, not a verified
    # interrupted production FFmpeg process or a safe deletion target.
