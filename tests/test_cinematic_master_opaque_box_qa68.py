"""QA68: strict offline master privacy must reject opaque top-level MP4 boxes.

Disposable genuine FFmpeg H.264, synthetic canary bytes, temporary SQLite.
This tests only top-level ISO-BMFF box inventory, not full MP4 sanitization.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / "tests" / "test_cinematic_master_audio_coverage_qa62.py"
spec = importlib.util.spec_from_file_location("qa62_helpers_for_qa68", HELPERS)
assert spec and spec.loader
qa62 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa62)
qa58 = qa62.qa58

CANARY = b"QA68_PRIVATE_CANARY_SYNTHETIC"


@pytest.mark.parametrize("case,expected_pass", [
    ("clean", True),
    ("opaque_free", False),
    ("opaque_uuid", False),
])
def test_strict_audit_rejects_hidden_top_level_mp4_payload(
    case, expected_pass, tmp_path, monkeypatch, capsys
):
    media, db, workspace = qa58._workspace(tmp_path)
    if case != "clean":
        payload = CANARY if case == "opaque_free" else b"1234567890ABCDEF" + CANARY
        box_type = b"free" if case == "opaque_free" else b"uuid"
        with media.open("ab") as stream:
            stream.write(struct.pack(">I4s", len(payload) + 8, box_type) + payload)
        assert CANARY in media.read_bytes()

    # The container is valid and FFprobe does not expose this opaque box as a
    # stream, chapter, or tag. Full H.264 video decode still succeeds.
    details = json.loads(subprocess.run([
        "ffprobe", "-v", "error", "-show_entries",
        "stream=codec_type,codec_name,nb_frames:stream_tags:"
        "format=duration:format_tags:chapter=start_time,end_time:chapter_tags",
        "-of", "json", str(media),
    ], check=True, capture_output=True, timeout=60).stdout)
    videos = [s for s in details["streams"] if s.get("codec_type") == "video"]
    assert len(videos) == 1
    assert videos[0]["codec_name"] == "h264"
    assert videos[0]["nb_frames"] == "48"
    assert abs(float(details["format"]["duration"]) - 2.0) < 0.05
    assert CANARY.decode() not in json.dumps(details)
    assert subprocess.run([
        qa58._require_ffmpeg(), "-nostdin", "-hide_banner", "-v", "error",
        "-xerror", "-protocol_whitelist", "file", "-i", str(media),
        "-map", "0:v:0", "-an", "-f", "null", "-",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
       timeout=60, check=False).returncode == 0

    qa58._record(db, 1, hashlib.sha256(media.read_bytes()).hexdigest())
    legacy_code, legacy = qa62._invoke(monkeypatch, capsys, workspace, db, False)
    assert legacy_code == 0
    assert legacy["verified_decodable_masters"] == 1
    assert legacy["timeline_attested_masters"] == 1
    assert legacy["timing_attested_masters"] == 1
    assert legacy["hash_attested_masters"] == 1

    strict_code, report = qa62._invoke(monkeypatch, capsys, workspace, db, True)
    assert strict_code == (0 if expected_pass else 1), (
        "FFprobe-visible metadata and persisted SHA do not attest opaque MP4 boxes"
    )
    assert report["integrity_attestation_complete"] is expected_pass
    assert report["opaque_mp4_payload_anomaly_count"] == (0 if expected_pass else 1)
    assert report["opaque_mp4_payload_unattested_count"] == 0
    assert CANARY.decode() not in json.dumps(report)
    assert report["safe_to_delete_automatically"] is False
