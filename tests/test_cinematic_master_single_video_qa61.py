"""QA61: strict completed-master attestation must reject ambiguous MP4 video tracks.

Genuine disposable FFmpeg H.264 media and temporary SQLite only. No owner
media, inference, cloud rendering or production assembly mutations.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / "tests" / "test_cinematic_master_sha_attestation_qa58.py"
spec = importlib.util.spec_from_file_location("qa58_helpers_for_qa61", HELPERS)
assert spec and spec.loader
qa58 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa58)
mod = qa58.mod


def _invoke(monkeypatch, capsys, workspace: Path, db: Path, *, strict: bool):
    argv = ["master-audit", "--workspace", str(workspace), "--database", str(db)]
    if strict:
        argv.append("--require-integrity")
    monkeypatch.setattr(sys, "argv", argv)
    exit_code = mod.main()
    report = json.loads(capsys.readouterr().out)
    qa58._assert_private(report)
    return exit_code, report


def test_single_video_track_remains_strictly_attested(tmp_path, monkeypatch, capsys):
    media, db, workspace = qa58._workspace(tmp_path)
    qa58._record(db, 1, hashlib.sha256(media.read_bytes()).hexdigest())
    code, report = _invoke(monkeypatch, capsys, workspace, db, strict=True)
    assert code == 0
    assert report["verified_decodable_masters"] == 1
    assert report["integrity_attestation_complete"] is True
    assert report["video_stream_anomaly_count"] == 0


def test_second_valid_video_track_is_not_mobile_safe_strict_attestation(
    tmp_path, monkeypatch, capsys
):
    media, db, workspace = qa58._workspace(tmp_path)
    replacement = workspace / "synthetic-second-video-track.mp4"
    subprocess.run([
        qa58._require_ffmpeg(), "-nostdin", "-hide_banner", "-loglevel", "error",
        "-i", str(media),
        "-f", "lavfi", "-i", "color=c=red:s=64x64:r=24:d=2",
        "-map", "0:v:0", "-map", "1:v:0",
        "-c:v:0", "copy", "-c:v:1", "libx264", "-bf", "0",
        "-pix_fmt", "yuv420p", "-frames:v:1", "48",
        "-movflags", "+faststart", "-y", str(replacement),
    ], check=True, capture_output=True, timeout=60)
    probe = json.loads(subprocess.run([
        "ffprobe", "-v", "error", "-show_entries",
        "stream=codec_type,nb_frames:format=duration",
        "-of", "json", str(replacement),
    ], check=True, capture_output=True, timeout=60).stdout)
    video_streams = [s for s in probe["streams"] if s.get("codec_type") == "video"]
    assert len(video_streams) == 2
    assert all(int(s["nb_frames"]) == 48 for s in video_streams)
    assert abs(float(probe["format"]["duration"]) - 2.0) < 0.05
    os.replace(replacement, media)
    qa58._record(db, 1, hashlib.sha256(media.read_bytes()).hexdigest())

    default_code, default_report = _invoke(
        monkeypatch, capsys, workspace, db, strict=False
    )
    assert default_code == 0  # legacy decode-only contract is preserved
    assert default_report["verified_decodable_masters"] == 1
    assert default_report["timeline_attested_masters"] == 1
    assert default_report["timing_attested_masters"] == 1
    assert default_report["hash_attested_masters"] == 1

    strict_code, strict_report = _invoke(
        monkeypatch, capsys, workspace, db, strict=True
    )
    assert strict_code == 1
    assert strict_report["integrity_attestation_complete"] is False
    assert strict_report["video_stream_anomaly_count"] == 1
