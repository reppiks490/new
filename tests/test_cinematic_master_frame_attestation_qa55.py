"""QA55: real synthetic FFmpeg frame parity versus persisted master timeline.

No owner media, model inference, private identifiers or production writes.
The existing QA54 full decode intentionally proves decodability, not frame parity.
"""
from __future__ import annotations

from contextlib import closing
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


def _setup(tmp_path: Path) -> tuple[Path, Path]:
    (tmp_path / "video-assets").mkdir()
    db = tmp_path / "studio.sqlite"
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("CREATE TABLE records (id TEXT PRIMARY KEY, kind TEXT, data TEXT, updated REAL)")
        conn.commit()
    return tmp_path, db


def _record(db: Path, ordinal: int, asset: str, frames: int | None,
            *, probe_frames: int | None = None) -> None:
    data = {"status": "ready", "asset_id": asset,
            "prompt": "PRIVATE_QA55_SCRIPT_SENTINEL"}
    if frames is not None:
        data["timeline_frames"] = frames
        data["probe"] = {"frame_count": frames if probe_frames is None else probe_frames}
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("INSERT INTO records VALUES(?,?,?,?)", (
            f"{ordinal:032x}", "video_master", json.dumps(data), float(ordinal),
        ))
        conn.commit()


def _encode(media: Path, frames: int = 48) -> None:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        if os.environ.get("CINEMATIC_REQUIRE_REAL_MEDIA") == "1":
            pytest.fail("Dedicated QA55 requires genuine FFmpeg and ffprobe")
        pytest.skip("Real FFmpeg unavailable in ordinary CI")
    subprocess.run([
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"testsrc2=s=64x64:r=24",
        "-frames:v", str(frames), "-an", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-y", str(media),
    ], check=True, capture_output=True, timeout=60)


def _private(report: dict) -> None:
    output = json.dumps(report)
    assert "PRIVATE_QA55_SCRIPT_SENTINEL" not in output
    assert ".mp4" not in output
    assert "video-assets" not in output
    assert report["safe_to_delete_automatically"] is False


def test_exact_48_frame_master_is_timeline_attested(tmp_path: Path) -> None:
    workspace, db = _setup(tmp_path)
    asset = "a" * 32
    _encode(workspace / "video-assets" / (asset + ".mp4"))
    _record(db, 1, asset, 48)
    report = mod.inspect(workspace, db)
    assert report["verification_complete"] is True
    assert report["verified_decodable_masters"] == 1
    assert report["timeline_attested_masters"] == 1
    assert report["timeline_unattested_masters"] == 0
    assert report["timeline_frame_mismatch_count"] == 0
    assert report["timeline_attestation_complete"] is True
    _private(report)


def test_decodable_short_master_cannot_pass_48_frame_timeline(tmp_path: Path) -> None:
    workspace, db = _setup(tmp_path)
    asset = "b" * 32
    _encode(workspace / "video-assets" / (asset + ".mp4"), frames=24)
    _record(db, 1, asset, 48)
    report = mod.inspect(workspace, db)
    # The original QA54 contract passes full decode; QA55 must distinguish parity.
    assert report["verification_complete"] is True
    assert report["verified_decodable_masters"] == 1
    assert report["timeline_attested_masters"] == 0
    assert report["timeline_frame_mismatch_count"] == 1
    assert report["timeline_attestation_complete"] is False
    _private(report)


def test_legacy_record_without_timeline_is_unattested_not_corrupt(tmp_path: Path) -> None:
    workspace, db = _setup(tmp_path)
    asset = "c" * 32
    _encode(workspace / "video-assets" / (asset + ".mp4"))
    _record(db, 1, asset, None)
    report = mod.inspect(workspace, db)
    assert report["verification_complete"] is True
    assert report["timeline_attested_masters"] == 0
    assert report["timeline_unattested_masters"] == 1
    assert report["timeline_frame_mismatch_count"] == 0
    assert report["timeline_attestation_complete"] is False
    _private(report)


def test_inconsistent_stored_probe_frame_count_is_unattested(tmp_path: Path) -> None:
    workspace, db = _setup(tmp_path)
    asset = "d" * 32
    _encode(workspace / "video-assets" / (asset + ".mp4"))
    _record(db, 1, asset, 48, probe_frames=24)
    report = mod.inspect(workspace, db)
    assert report["verified_decodable_masters"] == 1
    assert report["timeline_attested_masters"] == 0
    assert report["timeline_unattested_masters"] == 1
    assert report["timeline_attestation_complete"] is False
    _private(report)


def test_conflicting_duplicate_ready_attestations_fail_closed(tmp_path: Path) -> None:
    workspace, db = _setup(tmp_path)
    asset = "e" * 32
    _encode(workspace / "video-assets" / (asset + ".mp4"))
    _record(db, 1, asset, 48)
    _record(db, 2, asset, 24)
    report = mod.inspect(workspace, db)
    assert report["ready_master_records"] == 2
    assert report["unique_ready_assets"] == 1
    assert report["verified_decodable_masters"] == 1
    assert report["timeline_attested_masters"] == 0
    assert report["timeline_unattested_masters"] == 1
    assert report["timeline_attestation_complete"] is False
    _private(report)
