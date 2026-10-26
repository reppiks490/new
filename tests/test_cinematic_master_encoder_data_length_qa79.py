"""QA79: NUL-suffixed opaque bytes in the allowed MP4 encoder data box.

Disposable synthetic FFmpeg H.264 only. No owner media or model inference.
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
spec = importlib.util.spec_from_file_location(
    "qa78_helpers_for_qa79",
    ROOT / "tests" / "test_cinematic_master_encoder_item_privacy_qa78.py",
)
assert spec and spec.loader
qa78 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa78)
qa58, qa62 = qa78.qa58, qa78.qa62
CANARY = b"QA79_DISPOSABLE_PRIVATE_ENCODER_DATA_CANARY"


def _inject_hidden_data_suffix(media: Path, workspace: Path) -> None:
    # Place moov at EOF to avoid moving mdat chunk offsets during metadata edit.
    remux = workspace / "qa79-end-moov.mp4"
    subprocess.run([
        qa58._require_ffmpeg(), "-nostdin", "-hide_banner", "-loglevel", "error",
        "-i", str(media), "-map", "0:v:0", "-c:v", "copy", "-y", str(remux),
    ], check=True, capture_output=True, timeout=60)
    data = remux.read_bytes()

    def find_box(start: int, end: int, wanted: bytes) -> tuple[int, int]:
        cursor = start
        while cursor < end:
            assert end - cursor >= 8
            size = int.from_bytes(data[cursor:cursor + 4], "big")
            assert 8 <= size <= end - cursor
            if data[cursor + 4:cursor + 8] == wanted:
                return cursor, size
            cursor += size
        raise AssertionError(f"expected FFmpeg box missing: {wanted!r}")

    chain = []
    start, end = 0, len(data)
    for kind in (b"moov", b"udta", b"meta", b"ilst", b"\xa9too", b"data"):
        position, size = find_box(start, end, kind)
        chain.append((position, size))
        start = position + (12 if kind == b"meta" else 8)
        end = position + size
    assert chain[0][0] + chain[0][1] == len(data)
    data_position, data_size = chain[-1]
    assert data_size >= 16
    # A NUL terminates the FFprobe-visible Lavf encoder string, leaving a
    # private suffix inside the legitimate 'data' child, not a new box.
    suffix = b"\x00" + CANARY
    insert_at = data_position + data_size
    patched = data[:insert_at] + suffix + data[insert_at:]
    for position, size in chain:
        assert size + len(suffix) < 2**32
        patched = patched[:position] + struct.pack(">I", size + len(suffix)) + patched[position + 4:]
    media.write_bytes(patched)
    remux.unlink()
    assert suffix in media.read_bytes()


@pytest.mark.parametrize("case", ["clean", "hidden_encoder_data_suffix"])
def test_strict_audit_rejects_hidden_encoder_data_suffix(
    case, tmp_path, monkeypatch, capsys
):
    media, db, workspace = qa58._workspace(tmp_path)
    if case != "clean":
        _inject_hidden_data_suffix(media, workspace)

    probe = json.loads(subprocess.run([
        "ffprobe", "-v", "error", "-show_entries",
        "stream=codec_type,codec_name,nb_frames:stream_tags:"
        "format=duration:format_tags:chapter=start_time,end_time:chapter_tags",
        "-of", "json", str(media),
    ], check=True, capture_output=True, timeout=60).stdout)
    videos = [s for s in probe["streams"] if s.get("codec_type") == "video"]
    assert len(videos) == 1 and videos[0]["codec_name"] == "h264"
    assert videos[0]["nb_frames"] == "48"
    assert abs(float(probe["format"]["duration"]) - 2.0) < 0.05
    assert probe["format"]["tags"]["encoder"].startswith("Lavf")
    assert CANARY.decode() not in json.dumps(probe)

    decoded = subprocess.run([
        qa58._require_ffmpeg(), "-nostdin", "-hide_banner", "-v", "error",
        "-xerror", "-protocol_whitelist", "file", "-i", str(media),
        "-map", "0:v:0", "-an", "-f", "null", "-",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=60)
    assert decoded.returncode == 0

    qa58._record(db, 1, hashlib.sha256(media.read_bytes()).hexdigest())
    legacy_code, legacy = qa62._invoke(monkeypatch, capsys, workspace, db, False)
    assert legacy_code == 0
    assert legacy["verified_decodable_masters"] == 1
    assert legacy["hash_attested_masters"] == 1

    strict_code, report = qa62._invoke(monkeypatch, capsys, workspace, db, True)
    clean = case == "clean"
    assert strict_code == (0 if clean else 1), "NUL-hidden encoder data escaped strict audit"
    assert report["integrity_attestation_complete"] is clean
    assert report["freeform_metadata_anomaly_count"] == 0
    assert report["nested_mp4_payload_anomaly_count"] == (0 if clean else 1)
    assert report["nested_mp4_payload_unattested_count"] == 0
    assert CANARY.decode() not in json.dumps(report)
    assert report["safe_to_delete_automatically"] is False
