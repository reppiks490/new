"""QA54: genuine synthetic FFmpeg completed-master decode acceptance.

Offline, temporary SQLite + generated H.264 media only. No owner media or model
inference. Verify a nonempty truncated MP4 can pass ffprobe yet fail full decode.
"""
from __future__ import annotations

from contextlib import closing
import importlib.util
import json
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

def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    (tmp_path / "video-assets").mkdir()
    db = tmp_path / "studio.sqlite"
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("CREATE TABLE records (id TEXT PRIMARY KEY, kind TEXT, data TEXT, updated REAL)")
        conn.commit()
    return tmp_path, db

def _ready(db: Path, number: int, asset: str, *, status: str = "ready") -> None:
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("INSERT INTO records VALUES(?,?,?,?)", (
            f"{number:032x}", "video_master",
            json.dumps({"status": status, "asset_id": asset, "prompt": "PRIVATE_QA54_SCRIPT"}),
            float(number),
        ))
        conn.commit()

def _encode(path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg, "Dedicated QA54 requires genuine FFmpeg"
    subprocess.run([
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc2=s=64x64:r=24:d=2",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", "-y", str(path),
    ], check=True, capture_output=True, timeout=60)

def _private(result: dict) -> None:
    serialized = json.dumps(result)
    assert "PRIVATE_QA54_SCRIPT" not in serialized
    assert ".mp4" not in serialized
    assert not any("path" in key or "asset_id" in key for key in result)
    assert result["safe_to_delete_automatically"] is False

def test_genuine_complete_h264_is_fully_decodable(tmp_path: Path) -> None:
    workspace, db = _workspace(tmp_path)
    identifier = "a" * 32
    _encode(workspace / "video-assets" / (identifier + ".mp4"))
    _ready(db, 1, identifier)
    result = mod.inspect(workspace, db)
    assert result["ready_master_records"] == 1
    assert result["verified_decodable_masters"] == 1
    assert result["unverified_completed_masters"] == 0
    assert result["verification_complete"] is True
    _private(result)

def test_nonempty_truncated_faststart_master_fails_full_decode(tmp_path: Path) -> None:
    workspace, db = _workspace(tmp_path)
    identifier = "b" * 32
    media = workspace / "video-assets" / (identifier + ".mp4")
    _encode(media)
    original = media.read_bytes()
    media.write_bytes(original[: int(len(original) * 0.6)])
    assert media.stat().st_size > 128
    _ready(db, 1, identifier)
    # ffprobe can still read a faststart moov despite truncated media payload.
    result = mod.inspect(workspace, db)
    assert result["failed_decode_count"] == 1
    assert result["verified_decodable_masters"] == 0
    assert result["unverified_completed_masters"] == 1
    assert result["verification_complete"] is False
    _private(result)

def test_nonzero_garbage_completed_master_fails_probe(tmp_path: Path) -> None:
    workspace, db = _workspace(tmp_path)
    identifier = "c" * 32
    (workspace / "video-assets" / (identifier + ".mp4")).write_bytes(b"PRIVATE_QA54_SCRIPT" * 50)
    _ready(db, 1, identifier)
    result = mod.inspect(workspace, db)
    assert result["failed_probe_count"] == 1
    assert result["unverified_completed_masters"] == 1
    assert result["verification_complete"] is False
    _private(result)

def test_missing_and_symlink_masters_fail_closed(tmp_path: Path) -> None:
    workspace, db = _workspace(tmp_path)
    _ready(db, 1, "d" * 32)
    outside = tmp_path.parent / (tmp_path.name + "-PRIVATE_QA54_SCRIPT.mp4")
    outside.write_bytes(b"private")
    link = workspace / "video-assets" / ("e" * 32 + ".mp4")
    try:
        link.symlink_to(outside)
    except (NotImplementedError, OSError):
        pytest.skip("symlinks unavailable")
    _ready(db, 2, "e" * 32)
    result = mod.inspect(workspace, db)
    assert result["missing_or_unsafe_count"] == 2
    assert result["unverified_completed_masters"] == 2
    assert result["verification_complete"] is False
    assert outside.read_bytes() == b"private"
    _private(result)

def test_malformed_and_duplicate_ready_records_not_hidden(tmp_path: Path) -> None:
    workspace, db = _workspace(tmp_path)
    identifier = "f" * 32
    _encode(workspace / "video-assets" / (identifier + ".mp4"))
    _ready(db, 1, identifier)
    _ready(db, 2, identifier)
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("INSERT INTO records VALUES(?,?,?,?)", ("3" * 32, "video_master", "{invalid", 3.0))
        conn.commit()
    result = mod.inspect(workspace, db)
    assert result["ready_master_records"] == 2
    assert result["unique_ready_assets"] == 1
    assert result["verified_decodable_masters"] == 1
    assert result["malformed_or_invalid_records"] == 1
    assert result["verification_complete"] is False
    _private(result)
