"""QA64: AAC metadata can be valid while encoded audio packets fail decoding.

Only disposable real FFmpeg H.264/AAC media and temporary SQLite are used.
No owner footage, model inference, external services, or production changes.
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
spec = importlib.util.spec_from_file_location("qa62_helpers_for_qa64", HELPERS)
assert spec and spec.loader
qa62 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa62)
qa58 = qa62.qa58


def _decode(path: Path, kind: str) -> int:
    assert kind in {"video", "audio"}
    args = ["-map", "0:v:0", "-an", "-fps_mode", "passthrough"] if kind == "video" else [
        "-map", "0:a:0", "-vn",
    ]
    result = subprocess.run([
        qa58._require_ffmpeg(), "-nostdin", "-hide_banner", "-v", "error",
        "-xerror", "-protocol_whitelist", "file", "-i", str(path),
        *args, "-f", "null", "-",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
       timeout=60, check=False)
    # Some FFmpeg builds conceal damaged AAC and exit 0 while emitting
    # decoder errors at -v error. Neither condition is a clean decode.
    return result.returncode or (1 if result.stderr else 0)


@pytest.mark.parametrize("case,expected_pass", [
    ("video_only", True),
    ("clean_aac", True),
    ("corrupted_aac", False),
])
def test_strict_master_attests_decoded_aac_not_just_stream_metadata(
    case, expected_pass, tmp_path, monkeypatch, capsys
):
    media, db, workspace = qa58._workspace(tmp_path)
    if case != "video_only":
        replacement = workspace / "synthetic-audio-decode.mp4"
        subprocess.run([
            qa58._require_ffmpeg(), "-nostdin", "-hide_banner", "-loglevel", "error",
            "-i", str(media), "-f", "lavfi", "-t", "2",
            "-i", "sine=frequency=440:sample_rate=48000",
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
            "-y", str(replacement),
        ], check=True, capture_output=True, timeout=60)
        if case == "corrupted_aac":
            packet_data = json.loads(subprocess.run([
                "ffprobe", "-v", "error", "-select_streams", "a:0",
                "-show_packets", "-show_entries", "packet=pos,size",
                "-of", "json", str(replacement),
            ], check=True, capture_output=True, timeout=60).stdout)
            packets = packet_data["packets"]
            assert len(packets) >= 40, "Real AAC packets are required"
            blob = bytearray(replacement.read_bytes())
            # Replace payload bytes in mid-stream AAC packets, not MP4 atoms.
            # Packet positions come from genuine FFprobe, not mocked metadata.
            for packet in packets[15:35]:
                pos, size = int(packet["pos"]), int(packet["size"])
                assert pos > 0 and size > 0 and pos + size <= len(blob)
                blob[pos:pos + size] = b"\x00" * size
            replacement.write_bytes(blob)
        probe = json.loads(subprocess.run([
            "ffprobe", "-v", "error",
            "-show_entries", "stream=codec_type,codec_name,profile,start_time,duration:format=duration",
            "-of", "json", str(replacement),
        ], check=True, capture_output=True, timeout=60).stdout)
        audio = [s for s in probe["streams"] if s.get("codec_type") == "audio"]
        assert len(audio) == 1 and audio[0]["codec_name"] == "aac"
        assert audio[0]["profile"] == "LC"
        assert abs(float(audio[0]["start_time"])) <= 1 / 24
        assert abs(float(audio[0]["duration"]) - 2) <= 1 / 24
        assert abs(float(probe["format"]["duration"]) - 2) <= 1 / 24
        assert _decode(replacement, "video") == 0
        assert (_decode(replacement, "audio") == 0) is expected_pass
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
    assert report["audio_decode_anomaly_count"] == (1 if case == "corrupted_aac" else 0)
    assert report["audio_decode_unattested_count"] == 0
