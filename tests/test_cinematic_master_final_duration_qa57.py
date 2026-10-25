"""QA57: final-frame packet duration must not silently extend a cinematic master.

Uses disposable, genuine FFmpeg H.264 media and SQLite. Never owner media.
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


def _ffmpeg_tools() -> tuple[str, str]:
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        if os.environ.get("CINEMATIC_REQUIRE_REAL_MEDIA") == "1":
            pytest.fail("QA57 requires real FFmpeg and FFprobe")
        pytest.skip("FFmpeg unavailable in ordinary CI")
    return ffmpeg, ffprobe


def _fixture(tmp_path: Path, *, stretch_last_packet: bool) -> tuple[Path, Path]:
    ffmpeg, ffprobe = _ffmpeg_tools()
    media = tmp_path / "video-assets"
    media.mkdir()
    path = media / ("a" * 32 + ".mp4")
    source = tmp_path / "source.mp4"
    subprocess.run([
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc2=s=64x64:r=24",
        "-frames:v", "48", "-an", "-c:v", "libx264", "-bf", "0",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-y", str(source),
    ], check=True, capture_output=True, timeout=60)
    if stretch_last_packet:
        # Change only the last packet's duration, NOT its PTS or frame count.
        # Uses packet-relative DURATION, not a hardcoded container timebase.
        subprocess.run([
            ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
            "-i", str(source), "-map", "0:v:0", "-c:v", "copy",
            "-bsf:v", r"setts=duration=if(eq(N\,47)\,DURATION*48\,DURATION)",
            "-movflags", "+faststart", "-y", str(path),
        ], check=True, capture_output=True, timeout=60)
    else:
        shutil.copyfile(source, path)
    metadata = subprocess.run([
        ffprobe, "-v", "error", "-show_entries",
        "format=duration:stream=nb_frames", "-of", "json", str(path),
    ], check=True, capture_output=True, timeout=30)
    info = json.loads(metadata.stdout)
    assert int(info["streams"][0]["nb_frames"]) == 48
    duration = float(info["format"]["duration"])
    assert (duration > 3.5) if stretch_last_packet else (1.9 < duration < 2.1)

    db = tmp_path / "studio.sqlite"
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("CREATE TABLE records (id TEXT PRIMARY KEY, kind TEXT, data TEXT, updated REAL)")
        conn.execute("INSERT INTO records VALUES (?, ?, ?, ?)", (
            "1" * 32, "video_master", json.dumps({
                "status": "ready", "asset_id": "a" * 32,
                "timeline_frames": 48, "probe": {"frame_count": 48},
                "delivery_fps": 24, "prompt": "PRIVATE_QA57_SENTINEL",
            }), 1.0,
        ))
        conn.commit()
    return tmp_path, db


def _assert_private(report: dict) -> None:
    text = json.dumps(report)
    assert "PRIVATE_QA57_SENTINEL" not in text
    assert ".mp4" not in text and "video-assets" not in text
    assert not any("path" in k or "asset_id" in k for k in report)
    assert report["safe_to_delete_automatically"] is False


def test_normal_final_packet_duration_is_attested(tmp_path: Path) -> None:
    workspace, db = _fixture(tmp_path, stretch_last_packet=False)
    report = mod.inspect(workspace, db)
    assert report["verified_decodable_masters"] == 1
    assert report["timeline_attested_masters"] == 1
    assert report["timing_attested_masters"] == 1
    assert report["timing_anomaly_count"] == 0
    _assert_private(report)


def test_stretched_last_packet_decodes_with_correct_pts_but_fails_duration_attestation(
    tmp_path: Path,
) -> None:
    workspace, db = _fixture(tmp_path, stretch_last_packet=True)
    report = mod.inspect(workspace, db)
    # A real 48-frame MP4: successful full decode, correct PTS 0..47/24,
    # but the final frame is displayed for ~2s instead of 1/24s.
    assert report["verified_decodable_masters"] == 1
    assert report["timeline_attested_masters"] == 1
    assert report["timing_attested_masters"] == 0
    assert report["timing_anomaly_count"] == 1
    assert report["timing_attestation_complete"] is False
    _assert_private(report)
