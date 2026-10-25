"""QA69: reject privacy-bearing opaque MP4 boxes nested directly under moov.

Genuine synthetic FFmpeg H.264, temporary SQLite, no owner media/inference.
This is a narrow immediate-child test, not full recursive MP4 sanitization.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / "tests" / "test_cinematic_master_audio_coverage_qa62.py"
spec = importlib.util.spec_from_file_location("qa62_helpers_for_qa69", HELPERS)
assert spec and spec.loader
qa62 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa62)
qa58 = qa62.qa58

CANARY = b"QA69_PRIVATE_CANARY_SYNTHETIC"


def _inject_moov_child(media: Path, workspace: Path, kind: bytes) -> None:
    # Remux to place moov AFTER mdat. Inserting a child there preserves stco
    # offsets, so the test is a genuinely decodable MP4, not a broken fixture.
    remux = workspace / "qa69-end-moov.mp4"
    subprocess.run([
        qa58._require_ffmpeg(), "-nostdin", "-hide_banner", "-loglevel", "error",
        "-i", str(media), "-map", "0:v:0", "-c:v", "copy",
        "-y", str(remux),
    ], check=True, capture_output=True, timeout=60)
    data = remux.read_bytes()
    position = 0
    moov_offset = None
    moov_size = None
    while position < len(data):
        assert len(data) - position >= 8
        size = int.from_bytes(data[position:position + 4], "big")
        assert size >= 8 and position + size <= len(data)
        if data[position + 4:position + 8] == b"moov":
            moov_offset, moov_size = position, size
            break
        position += size
    assert moov_offset is not None and moov_size is not None
    assert moov_offset + moov_size == len(data), "moov must be after mdat"
    payload = CANARY if kind == b"free" else b"0123456789ABCDEF" + CANARY
    child = struct.pack(">I4s", 8 + len(payload), kind) + payload
    assert moov_size + len(child) < 2**32
    patched = (
        data[:moov_offset]
        + struct.pack(">I", moov_size + len(child))
        + data[moov_offset + 4:moov_offset + 8]
        + child
        + data[moov_offset + 8:]
    )
    media.write_bytes(patched)
    remux.unlink()
    assert CANARY in media.read_bytes()


@pytest.mark.parametrize("case,expected_pass", [
    ("clean", True),
    ("moov_free", False),
    ("moov_uuid", False),
])
def test_strict_master_rejects_opaque_moov_child(
    case, expected_pass, tmp_path, monkeypatch, capsys
):
    media, db, workspace = qa58._workspace(tmp_path)
    if case != "clean":
        _inject_moov_child(media, workspace, b"free" if case == "moov_free" else b"uuid")

    probe = json.loads(subprocess.run([
        "ffprobe", "-v", "error",
        "-show_entries",
        "stream=codec_type,codec_name,nb_frames:stream_tags:"
        "format=duration:format_tags:chapter=start_time,end_time:chapter_tags",
        "-of", "json", str(media),
    ], check=True, capture_output=True, timeout=60).stdout)
    video = [s for s in probe["streams"] if s.get("codec_type") == "video"]
    assert len(video) == 1
    assert video[0]["codec_name"] == "h264"
    assert video[0]["nb_frames"] == "48"
    assert abs(float(probe["format"]["duration"]) - 2) < 0.05
    assert CANARY.decode() not in json.dumps(probe)
    decode = subprocess.run([
        qa58._require_ffmpeg(), "-nostdin", "-hide_banner", "-v", "error",
        "-xerror", "-protocol_whitelist", "file", "-i", str(media),
        "-map", "0:v:0", "-an", "-f", "null", "-",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=60)
    assert decode.returncode == 0, "fixture must fully decode"

    qa58._record(db, 1, hashlib.sha256(media.read_bytes()).hexdigest())
    legacy_code, legacy = qa62._invoke(monkeypatch, capsys, workspace, db, False)
    assert legacy_code == 0
    assert legacy["verified_decodable_masters"] == 1
    assert legacy["timeline_attested_masters"] == 1
    assert legacy["timing_attested_masters"] == 1
    assert legacy["hash_attested_masters"] == 1
    assert legacy["opaque_mp4_payload_anomaly_count"] == 0

    strict_code, report = qa62._invoke(monkeypatch, capsys, workspace, db, True)
    assert strict_code == (0 if expected_pass else 1), (
        "FFprobe metadata and top-level MP4 checks miss opaque moov child payload"
    )
    assert report["integrity_attestation_complete"] is expected_pass
    assert report["nested_mp4_payload_anomaly_count"] == (0 if expected_pass else 1)
    assert report["nested_mp4_payload_unattested_count"] == 0
    assert CANARY.decode() not in json.dumps(report)
    assert report["safe_to_delete_automatically"] is False
