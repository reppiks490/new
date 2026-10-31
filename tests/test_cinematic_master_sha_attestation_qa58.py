"""QA58: a decodable, frame/timestamp-correct master may contradict its stored SHA.

Disposable genuine synthetic H.264 media + SQLite only. No owner files or inference.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "cinematic_completed_master_decode_qa54.py"
spec = importlib.util.spec_from_file_location("cinematic_completed_master_decode_qa54", TOOL)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def _require_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not shutil.which("ffprobe"):
        if os.environ.get("CINEMATIC_REQUIRE_REAL_MEDIA") == "1":
            pytest.fail("QA58 requires genuine FFmpeg and FFprobe")
        pytest.skip("FFmpeg unavailable in ordinary CI")
    return ffmpeg


def _workspace(tmp_path: Path) -> tuple[Path, Path, Path]:
    ffmpeg = _require_ffmpeg()
    media_dir = tmp_path / "video-assets"
    media_dir.mkdir()
    media = media_dir / ("a" * 32 + ".mp4")
    subprocess.run([
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc2=s=64x64:r=24",
        "-frames:v", "48", "-an", "-c:v", "libx264", "-bf", "0",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-y", str(media),
    ], check=True, capture_output=True, timeout=60)
    db = tmp_path / "studio.sqlite"
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("CREATE TABLE records (id TEXT PRIMARY KEY, kind TEXT, data TEXT, updated REAL)")
        conn.commit()
    return media, db, tmp_path


def _record(db: Path, number: int, digest: str | None) -> None:
    data = {
        "status": "ready", "asset_id": "a" * 32,
        "timeline_frames": 48, "probe": {"frame_count": 48},
        "delivery_fps": 24, "prompt": "PRIVATE_QA58_PROMPT_SENTINEL",
    }
    if digest is not None:
        data["sha256"] = digest
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("INSERT INTO records VALUES(?,?,?,?)", (
            f"{number:032x}", "video_master", json.dumps(data), float(number),
        ))
        conn.commit()


def _assert_private(report: dict) -> None:
    payload = json.dumps(report)
    assert "PRIVATE_QA58_PROMPT_SENTINEL" not in payload
    assert ".mp4" not in payload and "video-assets" not in payload
    assert not any("path" in key or "asset_id" in key or "sha256" in key for key in report)
    assert report["safe_to_delete_automatically"] is False


def test_correct_stored_sha_attests_decodable_timed_master(tmp_path: Path) -> None:
    media, db, workspace = _workspace(tmp_path)
    _record(db, 1, hashlib.sha256(media.read_bytes()).hexdigest())
    report = mod.inspect(workspace, db)
    assert report["verified_decodable_masters"] == 1
    assert report["timing_attested_masters"] == 1
    assert report.get("hash_attested_masters") == 1
    assert report.get("hash_mismatch_count") == 0
    assert report.get("hash_attestation_complete") is True
    _assert_private(report)


def test_decodable_timed_master_with_changed_bytes_fails_sha_attestation(tmp_path: Path) -> None:
    media, db, workspace = _workspace(tmp_path)
    original_sha = hashlib.sha256(media.read_bytes()).hexdigest()
    _record(db, 1, original_sha)
    replacement = workspace / "replacement.mp4"
    subprocess.run([
        _require_ffmpeg(), "-nostdin", "-hide_banner", "-loglevel", "error",
        "-i", str(media), "-map", "0:v:0", "-c:v", "copy",
        "-metadata", "comment=QA58_SYNTHETIC_REWRAP",
        "-movflags", "+faststart", "-y", str(replacement),
    ], check=True, capture_output=True, timeout=60)
    assert hashlib.sha256(replacement.read_bytes()).hexdigest() != original_sha
    os.replace(replacement, media)
    report = mod.inspect(workspace, db)
    assert report["verified_decodable_masters"] == 1
    assert report["timeline_attested_masters"] == 1
    assert report["timing_attested_masters"] == 1
    assert report.get("hash_attested_masters") == 0
    assert report.get("hash_mismatch_count") == 1
    assert report.get("hash_attestation_complete") is False
    _assert_private(report)


def test_legacy_master_without_sha_is_unattested_not_corrupt(tmp_path: Path) -> None:
    media, db, workspace = _workspace(tmp_path)
    _record(db, 1, None)
    report = mod.inspect(workspace, db)
    assert report["verified_decodable_masters"] == 1
    assert report.get("hash_unattested_masters") == 1
    assert report.get("hash_mismatch_count") == 0
    assert report.get("hash_attestation_complete") is False
    _assert_private(report)


def test_conflicting_duplicate_sha_claims_fail_closed(tmp_path: Path) -> None:
    media, db, workspace = _workspace(tmp_path)
    _record(db, 1, hashlib.sha256(media.read_bytes()).hexdigest())
    _record(db, 2, "0" * 64)
    report = mod.inspect(workspace, db)
    assert report["verified_decodable_masters"] == 1
    assert report.get("hash_attested_masters") == 0
    assert report.get("hash_unattested_masters") == 1
    assert report.get("hash_mismatch_count") == 0
    _assert_private(report)


def test_invalid_stored_sha_is_unattested_not_false_match(tmp_path: Path) -> None:
    media, db, workspace = _workspace(tmp_path)
    _record(db, 1, "not-a-sha256")
    report = mod.inspect(workspace, db)
    assert report["verified_decodable_masters"] == 1
    assert report.get("hash_attested_masters") == 0
    assert report.get("hash_unattested_masters") == 1
    assert report.get("hash_mismatch_count") == 0
    _assert_private(report)
