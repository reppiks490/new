"""QA109: opt-in *real* Linux FFmpeg preflight and synthetic local encode.

The preflight itself remains read-only. This independent acceptance test then
creates ONLY a disposable two-second lavfi color clip, probes it and fully
decodes it. No owner media, models, cloud, Windows/WSL2 or phone is exercised.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from app.video.cinematic_local_media_preflight_qa105 import audit_local_media_runtime


pytestmark = pytest.mark.skipif(
    os.environ.get("CINEMATIC_REAL_PREFLIGHT_QA109") != "1",
    reason="opt-in isolated real-FFmpeg QA109 acceptance only",
)


def _run(argv: list[str], *, timeout: int = 45) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv, check=True, capture_output=True, timeout=timeout,
    )


def test_real_toolchain_preflight_then_disposable_h264_encode(tmp_path: Path):
    """Verify the actual CI toolchain, not mocks or an owner workstation."""
    assert shutil.which("ffmpeg"), "Real FFmpeg required for opt-in QA109"
    assert shutil.which("ffprobe"), "Real FFprobe required for opt-in QA109"

    before = set(tmp_path.iterdir())
    report = audit_local_media_runtime(workspace=tmp_path, min_free_gib=1)
    assert report["schema_version"] == 1
    assert report["limited_ready"] is True, report["checks"]
    assert report["release_ready"] is False
    assert {c["name"]: c["status"] for c in report["checks"]} == {
        "ffmpeg_binary": "passed",
        "ffprobe_binary": "passed",
        "h264_encoder": "passed",
        "workspace_disk": "passed",
    }
    assert set(tmp_path.iterdir()) == before, "Read-only preflight wrote files"
    assert "MODEL_INFERENCE_NOT_TESTED" in report["not_verified"]
    assert "PHYSICAL_MOBILE_PLAYBACK_NOT_TESTED" in report["not_verified"]
    assert "WINDOWS_WSL2_PERFORMANCE_NOT_TESTED" in report["not_verified"]

    output = tmp_path / "qa109-synthetic-only.mp4"
    _run([
        "ffmpeg", "-nostdin", "-y", "-v", "error",
        "-f", "lavfi", "-i", "color=c=blue:s=160x90:r=24:d=2",
        "-an", "-frames:v", "48", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(output),
    ], timeout=60)
    assert output.is_file() and output.stat().st_size > 1000
    with output.open("rb") as f:
        digest = hashlib.file_digest(f, "sha256").hexdigest()
    assert len(digest) == 64

    metadata = json.loads(_run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries",
        "stream=codec_name,pix_fmt,avg_frame_rate,nb_frames,width,height:"
        "format=duration",
        "-of", "json", str(output),
    ]).stdout)
    stream = metadata["streams"][0]
    assert stream["codec_name"] == "h264"
    assert stream["pix_fmt"] == "yuv420p"
    assert stream["avg_frame_rate"] == "24/1"
    assert stream["width"] == 160 and stream["height"] == 90
    assert int(stream["nb_frames"]) == 48
    assert float(metadata["format"]["duration"]) == pytest.approx(2.0, abs=0.05)

    # Decoding all frames checks more than an MP4 header or an encoder listing.
    _run([
        "ffmpeg", "-nostdin", "-v", "error", "-xerror",
        "-i", str(output), "-map", "0:v:0", "-an",
        "-f", "null", "-",
    ], timeout=60)
