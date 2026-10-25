"""QA67: a structurally allowed MP4 encoder tag can still carry private text.

Only disposable FFmpeg H.264 footage, synthetic canaries, and temporary SQLite
records. This is an offline strict-audit regression, not owner-media proof.
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
spec = importlib.util.spec_from_file_location("qa62_helpers_for_qa67", HELPERS)
assert spec and spec.loader
qa62 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa62)
qa58 = qa62.qa58

CANARY = "QA67_PRIVATE_CANARY"


@pytest.mark.parametrize("encoder_tag,expected_pass", [
    (None, True),
    (CANARY, False),
    ("Lavc61.19.101 " + CANARY, False),
])
def test_strict_audit_rejects_private_encoder_tag_values(
    encoder_tag, expected_pass, tmp_path, monkeypatch, capsys
):
    media, db, workspace = qa58._workspace(tmp_path)
    if encoder_tag is not None:
        replacement = workspace / "qa67-synthetic-remux.mp4"
        subprocess.run([
            qa58._require_ffmpeg(), "-nostdin", "-hide_banner",
            "-loglevel", "error", "-i", str(media),
            "-map", "0:v:0", "-c:v", "copy",
            "-metadata:s:v:0", "encoder=" + encoder_tag,
            "-movflags", "+faststart", "-y", str(replacement),
        ], check=True, capture_output=True, timeout=60)
        os.replace(replacement, media)

    details = json.loads(subprocess.run([
        "ffprobe", "-v", "error",
        "-show_entries", "stream=codec_type,codec_name,nb_frames:stream_tags:"
        "format=duration:format_tags", "-of", "json", str(media),
    ], check=True, capture_output=True, timeout=60).stdout)
    videos = [s for s in details["streams"] if s.get("codec_type") == "video"]
    assert len(videos) == 1
    assert videos[0]["codec_name"] == "h264"
    assert videos[0]["nb_frames"] == "48"
    assert abs(float(details["format"]["duration"]) - 2.0) < 0.05
    if encoder_tag is not None:
        # FFmpeg can truncate MP4 encoder tags to 31 bytes. The canary
        # remains present and demonstrates private text in a permitted key.
        actual = videos[0]["tags"]["encoder"]
        assert actual != "" and actual not in ("Lavc61.19.101 libx264",)
        assert (CANARY in actual) or actual.startswith("Lavc61.19.101 QA67")
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
        "An allowed MP4 tag key must not exempt arbitrary private tag values"
    )
    assert report["integrity_attestation_complete"] is expected_pass
    assert report["freeform_metadata_anomaly_count"] == (0 if expected_pass else 1)
    assert CANARY not in json.dumps(report)
    assert report["safe_to_delete_automatically"] is False
