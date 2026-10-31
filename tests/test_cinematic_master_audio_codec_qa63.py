"""QA63: strict mobile master audit must not accept non-AAC audio in MP4.

Real disposable FFmpeg H.264/AAC/MP3 media and temporary SQLite only.
No owner media, model inference, network transfer, or production mutation.
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
spec = importlib.util.spec_from_file_location("qa62_helpers_for_qa63", HELPERS)
assert spec and spec.loader
qa62 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa62)
qa58 = qa62.qa58


@pytest.mark.parametrize("case,expected_pass", [
    ("video_only", True),
    ("aac_lc", True),
    ("mp3_in_mp4", False),
])
def test_mobile_master_requires_aac_lc_when_audio_is_present(
    case, expected_pass, tmp_path, monkeypatch, capsys
):
    media, db, workspace = qa58._workspace(tmp_path)
    if case != "video_only":
        replacement = workspace / "synthetic-codec-test.mp4"
        encoder = "aac" if case == "aac_lc" else "libmp3lame"
        subprocess.run([
            qa58._require_ffmpeg(), "-nostdin", "-hide_banner", "-loglevel", "error",
            "-i", str(media), "-f", "lavfi", "-t", "2",
            "-i", "sine=frequency=440:sample_rate=48000",
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
            "-c:a", encoder, "-b:a", "128k", "-movflags", "+faststart",
            "-y", str(replacement),
        ], check=True, capture_output=True, timeout=60)
        probe = json.loads(subprocess.run([
            "ffprobe", "-v", "error",
            "-show_entries", "stream=codec_type,codec_name,profile,start_time,duration:format=duration",
            "-of", "json", str(replacement),
        ], check=True, capture_output=True, timeout=60).stdout)
        audio = [s for s in probe["streams"] if s.get("codec_type") == "audio"]
        assert len(audio) == 1
        assert audio[0]["codec_name"] == ("aac" if case == "aac_lc" else "mp3")
        if case == "aac_lc":
            assert audio[0]["profile"] == "LC"
        assert abs(float(audio[0]["start_time"])) < 1 / 24
        assert abs(float(audio[0]["duration"]) - 2) <= 1 / 24
        assert abs(float(probe["format"]["duration"]) - 2) <= 1 / 24
        os.replace(replacement, media)

    qa58._record(db, 1, hashlib.sha256(media.read_bytes()).hexdigest())
    legacy_code, legacy = qa62._invoke(monkeypatch, capsys, workspace, db, False)
    assert legacy_code == 0
    assert legacy["verified_decodable_masters"] == 1
    assert legacy["timeline_attested_masters"] == 1
    assert legacy["timing_attested_masters"] == 1
    assert legacy["hash_attested_masters"] == 1
    strict_code, report = qa62._invoke(monkeypatch, capsys, workspace, db, True)
    assert strict_code == (0 if expected_pass else 1)
    assert report["integrity_attestation_complete"] is expected_pass
    assert report["audio_codec_anomaly_count"] == (1 if case == "mp3_in_mp4" else 0)
    assert report["audio_codec_unattested_count"] == 0
