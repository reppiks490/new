"""QA65: a decodable/timed/hash-matching MP4 can violate mobile video format.

Disposable real FFmpeg video and temporary SQLite only; no owner footage,
model inference, production service changes, or physical phone claim.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / "tests" / "test_cinematic_master_audio_coverage_qa62.py"
spec = importlib.util.spec_from_file_location("qa62_helpers_for_qa65", HELPERS)
assert spec and spec.loader
qa62 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa62)
qa58 = qa62.qa58


@pytest.mark.parametrize("case,codec,pix_fmt,expected_pass", [
    ("h264_420", "h264", "yuv420p", True),
    ("mpeg4_420", "mpeg4", "yuv420p", False),
    ("h264_444", "h264", "yuv444p", False),
])
def test_strict_master_requires_h264_8bit_420_mobile_video(
    case, codec, pix_fmt, expected_pass, tmp_path, monkeypatch, capsys
):
    media, db, workspace = qa58._workspace(tmp_path)
    if case != "h264_420":
        replacement = workspace / "synthetic-video-format.mp4"
        subprocess.run([
            qa58._require_ffmpeg(), "-nostdin", "-hide_banner", "-loglevel", "error",
            "-i", str(media), "-map", "0:v:0", "-an",
            "-c:v", "mpeg4" if codec == "mpeg4" else "libx264",
            "-pix_fmt", pix_fmt, "-bf", "0", "-r", "24",
            "-frames:v", "48", "-movflags", "+faststart",
            "-y", str(replacement),
        ], check=True, capture_output=True, timeout=60)
        os.replace(replacement, media)

    details = json.loads(subprocess.run([
        "ffprobe", "-v", "error",
        "-show_entries", "stream=codec_type,codec_name,pix_fmt,nb_frames,avg_frame_rate:format=duration",
        "-of", "json", str(media),
    ], check=True, capture_output=True, timeout=60).stdout)
    video = [s for s in details["streams"] if s.get("codec_type") == "video"]
    assert len(video) == 1
    assert video[0]["codec_name"] == codec
    assert video[0]["pix_fmt"] == pix_fmt
    assert video[0]["nb_frames"] == "48"
    assert video[0]["avg_frame_rate"] == "24/1"
    assert abs(float(details["format"]["duration"]) - 2.0) < 0.05
    assert subprocess.run([
        qa58._require_ffmpeg(), "-nostdin", "-hide_banner", "-v", "error",
        "-xerror", "-protocol_whitelist", "file", "-i", str(media),
        "-map", "0:v:0", "-an", "-f", "null", "-",
    ], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
       timeout=60).returncode == 0

    qa58._record(db, 1, hashlib.sha256(media.read_bytes()).hexdigest())
    legacy_code, legacy = qa62._invoke(monkeypatch, capsys, workspace, db, False)
    assert legacy_code == 0
    assert legacy["verified_decodable_masters"] == 1
    assert legacy["timeline_attested_masters"] == 1
    assert legacy["timing_attested_masters"] == 1
    assert legacy["hash_attested_masters"] == 1

    strict_code, report = qa62._invoke(monkeypatch, capsys, workspace, db, True)
    assert strict_code == (0 if expected_pass else 1), (
        "Decoding, frame parity, PTS and SHA are not mobile codec/pixel proof"
    )
    assert report["integrity_attestation_complete"] is expected_pass
    assert report["video_codec_anomaly_count"] == (1 if codec == "mpeg4" else 0)
    assert report["video_codec_unattested_count"] == 0
    assert report["video_pixel_format_anomaly_count"] == (1 if pix_fmt == "yuv444p" else 0)
    assert report["video_pixel_format_unattested_count"] == 0
