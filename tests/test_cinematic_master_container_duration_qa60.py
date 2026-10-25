"""QA60: a valid 2-second video timeline must not attest a 5-second MP4 container.

Real disposable FFmpeg H.264/AAC and SQLite only. No owner media, inference,
cloud services or changes to the production assembler.
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
spec = importlib.util.spec_from_file_location("qa58_helpers_for_qa60", HELPERS)
assert spec and spec.loader
qa58 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa58)
mod = qa58.mod


def _strict(monkeypatch, capsys, workspace: Path, db: Path):
    monkeypatch.setattr(sys, "argv", [
        "master-audit", "--workspace", str(workspace),
        "--database", str(db), "--require-integrity",
    ])
    code = mod.main()
    report = json.loads(capsys.readouterr().out)
    qa58._assert_private(report)
    return code, report


def test_clean_two_second_container_still_attests(tmp_path, monkeypatch, capsys):
    media, db, workspace = qa58._workspace(tmp_path)
    qa58._record(db, 1, hashlib.sha256(media.read_bytes()).hexdigest())
    code, report = _strict(monkeypatch, capsys, workspace, db)
    assert code == 0
    assert report["integrity_attestation_complete"] is True
    assert report["timing_attested_masters"] == 1


def test_five_second_container_tail_cannot_pass_two_second_timeline(
    tmp_path, monkeypatch, capsys
):
    media, db, workspace = qa58._workspace(tmp_path)
    replacement = workspace / "synthetic-long-audio.mp4"
    subprocess.run([
        qa58._require_ffmpeg(), "-nostdin", "-hide_banner", "-loglevel", "error",
        "-i", str(media),
        "-f", "lavfi", "-i", "anullsrc=channel_layout=mono:sample_rate=48000",
        "-t", "5", "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac", "-movflags", "+faststart",
        "-y", str(replacement),
    ], check=True, capture_output=True, timeout=60)
    details = json.loads(subprocess.run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration:stream=codec_type,duration",
        "-of", "json", str(replacement),
    ], check=True, capture_output=True, timeout=60).stdout)
    assert float(details["format"]["duration"]) > 4.5
    video = [s for s in details["streams"] if s.get("codec_type") == "video"]
    assert len(video) == 1 and abs(float(video[0]["duration"]) - 2.0) < 0.05
    os.replace(replacement, media)
    qa58._record(db, 1, hashlib.sha256(media.read_bytes()).hexdigest())

    code, report = _strict(monkeypatch, capsys, workspace, db)
    # Video bytes, decoded frame count, per-frame PTS/duration and stored hash
    # are all valid; only the overall MP4 playback duration contradicts 2 s.
    assert report["verified_decodable_masters"] == 1
    assert report["timeline_attested_masters"] == 1
    assert report["hash_attested_masters"] == 1
    assert report["timing_anomaly_count"] == 1
    assert report["timing_attested_masters"] == 0
    assert report["integrity_attestation_complete"] is False
    assert code == 1
