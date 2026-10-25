"""QA62: strict offline cinematic masters must not silently omit or delay audio.

Genuine disposable H.264/AAC FFmpeg media and temporary SQLite only.
No owner media, model inference, cloud generation, or production mutations.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / "tests" / "test_cinematic_master_sha_attestation_qa58.py"
spec = importlib.util.spec_from_file_location("qa58_helpers_for_qa62", HELPERS)
assert spec and spec.loader
qa58 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa58)
mod = qa58.mod


def _invoke(monkeypatch, capsys, workspace, db, strict):
    argv = ["master-audit", "--workspace", str(workspace), "--database", str(db)]
    if strict:
        argv.append("--require-integrity")
    monkeypatch.setattr(sys, "argv", argv)
    code = mod.main()
    report = json.loads(capsys.readouterr().out)
    qa58._assert_private(report)
    return code, report


@pytest.mark.parametrize("case,expected_pass", [
    ("video_only", True),
    ("full_audio", True),
    ("short_audio", False),
    ("delayed_audio", False),
    ("two_audio_tracks", False),
])
def test_audio_stream_coverage_is_part_of_strict_master_attestation(
    case, expected_pass, tmp_path, monkeypatch, capsys
):
    media, db, workspace = qa58._workspace(tmp_path)
    if case != "video_only":
        replacement = workspace / "synthetic-audio-coverage.mp4"
        cmd = [
            qa58._require_ffmpeg(), "-nostdin", "-hide_banner", "-loglevel", "error",
            "-i", str(media),
        ]
        if case == "delayed_audio":
            cmd += ["-itsoffset", "1", "-f", "lavfi", "-t", "1",
                    "-i", "anullsrc=channel_layout=mono:sample_rate=48000"]
        else:
            cmd += ["-f", "lavfi", "-t", "0.5" if case == "short_audio" else "2",
                    "-i", "anullsrc=channel_layout=mono:sample_rate=48000"]
        if case == "two_audio_tracks":
            cmd += ["-f", "lavfi", "-t", "2",
                    "-i", "sine=frequency=440:sample_rate=48000"]
        cmd += ["-map", "0:v:0", "-map", "1:a:0"]
        if case == "two_audio_tracks":
            cmd += ["-map", "2:a:0"]
        cmd += ["-c:v", "copy", "-c:a", "aac", "-movflags", "+faststart",
                "-y", str(replacement)]
        subprocess.run(cmd, check=True, capture_output=True, timeout=60)
        details = json.loads(subprocess.run([
            "ffprobe", "-v", "error",
            "-show_entries", "stream=codec_type,start_time,duration:format=duration",
            "-of", "json", str(replacement),
        ], check=True, capture_output=True, timeout=60).stdout)
        assert abs(float(details["format"]["duration"]) - 2.0) < 0.05
        audio = [s for s in details["streams"] if s.get("codec_type") == "audio"]
        assert len(audio) == (2 if case == "two_audio_tracks" else 1)
        if case == "short_audio":
            assert float(audio[0]["duration"]) < 0.75
        if case == "delayed_audio":
            assert float(audio[0]["start_time"]) > 0.75
        os.replace(replacement, media)

    qa58._record(db, 1, hashlib.sha256(media.read_bytes()).hexdigest())
    legacy_code, legacy = _invoke(monkeypatch, capsys, workspace, db, False)
    assert legacy_code == 0
    assert legacy["verified_decodable_masters"] == 1
    assert legacy["timeline_attested_masters"] == 1
    assert legacy["timing_attested_masters"] == 1
    assert legacy["hash_attested_masters"] == 1

    code, report = _invoke(monkeypatch, capsys, workspace, db, True)
    assert code == (0 if expected_pass else 1)
    assert report["integrity_attestation_complete"] is expected_pass
    assert report["audio_stream_anomaly_count"] == (1 if case == "two_audio_tracks" else 0)
    assert report["audio_timing_anomaly_count"] == (
        1 if case in ("short_audio", "delayed_audio") else 0
    )
    assert report["audio_timing_unattested_count"] == 0
