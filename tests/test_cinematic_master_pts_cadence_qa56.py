"""QA56: genuine synthetic PTS cadence acceptance for completed cinematic masters.

A full decode and frame-count parity can both pass while presentation timestamps
have gaps or drift. This is an offline-only diagnostic; no owner media.
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


def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    (tmp_path / "video-assets").mkdir()
    db = tmp_path / "studio.sqlite"
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("CREATE TABLE records (id TEXT PRIMARY KEY, kind TEXT, data TEXT, updated REAL)")
        conn.commit()
    return tmp_path, db


def _record(db: Path, ordinal: int, asset: str, fps: int | None = 24) -> None:
    data = {
        "status": "ready", "asset_id": asset, "timeline_frames": 48,
        "probe": {"frame_count": 48}, "prompt": "PRIVATE_QA56_PROMPT_SENTINEL",
    }
    if fps is not None:
        data["delivery_fps"] = fps
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("INSERT INTO records VALUES(?,?,?,?)", (
            f"{ordinal:032x}", "video_master", json.dumps(data), float(ordinal),
        ))
        conn.commit()


def _encode(path: Path, *, warped: bool = False) -> None:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        if os.environ.get("CINEMATIC_REQUIRE_REAL_MEDIA") == "1":
            pytest.fail("Dedicated QA56 requires genuine FFmpeg and ffprobe")
        pytest.skip("FFmpeg and ffprobe unavailable in ordinary CI")
    cmd = [
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc2=s=64x64:r=24",
    ]
    if warped:
        cmd += ["-vf", "setpts=2*PTS"]
    cmd += [
        "-frames:v", "48", "-fps_mode", "passthrough",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", "-y", str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=60)


def _private(report: dict) -> None:
    serialized = json.dumps(report)
    assert "PRIVATE_QA56_PROMPT_SENTINEL" not in serialized
    assert ".mp4" not in serialized
    assert "video-assets" not in serialized
    assert not any("path" in key or "asset_id" in key for key in report)
    assert report["safe_to_delete_automatically"] is False


def test_regular_48_frame_24fps_master_has_pts_cadence_attestation(tmp_path: Path) -> None:
    workspace, db = _workspace(tmp_path)
    asset = "a" * 32
    _encode(workspace / "video-assets" / (asset + ".mp4"))
    _record(db, 1, asset)
    report = mod.inspect(workspace, db)
    assert report["timeline_attested_masters"] == 1
    assert report["timing_attested_masters"] == 1
    assert report["timing_unattested_masters"] == 0
    assert report["timing_anomaly_count"] == 0
    assert report["timing_attestation_complete"] is True
    _private(report)


def test_warped_pts_decodes_and_matches_frame_count_but_fails_timing(tmp_path: Path) -> None:
    workspace, db = _workspace(tmp_path)
    asset = "b" * 32
    _encode(workspace / "video-assets" / (asset + ".mp4"), warped=True)
    _record(db, 1, asset)
    report = mod.inspect(workspace, db)
    assert report["verified_decodable_masters"] == 1
    assert report["timeline_attested_masters"] == 1
    assert report["timing_attested_masters"] == 0
    assert report["timing_anomaly_count"] == 1
    assert report["timing_attestation_complete"] is False
    _private(report)


def test_wrong_persisted_fps_does_not_pass_pts_cadence(tmp_path: Path) -> None:
    workspace, db = _workspace(tmp_path)
    asset = "c" * 32
    _encode(workspace / "video-assets" / (asset + ".mp4"))
    _record(db, 1, asset, fps=25)
    report = mod.inspect(workspace, db)
    assert report["timeline_attested_masters"] == 1
    assert report["timing_anomaly_count"] == 1
    assert report["timing_attestation_complete"] is False
    _private(report)


def test_missing_legacy_delivery_fps_is_unattested_not_corrupt(tmp_path: Path) -> None:
    workspace, db = _workspace(tmp_path)
    asset = "d" * 32
    _encode(workspace / "video-assets" / (asset + ".mp4"))
    _record(db, 1, asset, fps=None)
    report = mod.inspect(workspace, db)
    assert report["timeline_attested_masters"] == 1
    assert report["timing_attested_masters"] == 0
    assert report["timing_unattested_masters"] == 1
    assert report["timing_anomaly_count"] == 0
    assert report["timing_attestation_complete"] is False
    _private(report)


def test_conflicting_duplicate_delivery_fps_is_unattested(tmp_path: Path) -> None:
    workspace, db = _workspace(tmp_path)
    asset = "e" * 32
    _encode(workspace / "video-assets" / (asset + ".mp4"))
    _record(db, 1, asset, fps=24)
    _record(db, 2, asset, fps=25)
    report = mod.inspect(workspace, db)
    assert report["timeline_attested_masters"] == 1
    assert report["timing_attested_masters"] == 0
    assert report["timing_unattested_masters"] == 1
    assert report["timing_anomaly_count"] == 0
    assert report["timing_attestation_complete"] is False
    _private(report)
