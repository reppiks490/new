"""QA71: strict offline master integrity must reject opaque MP4 mdia children.

Synthetic 48-frame H.264 FFmpeg media, private temporary SQLite; no owner
media, cloud inference, or actual mobile playback. This is not a full sanitizer.
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
HELPERS = ROOT / "tests" / "test_cinematic_master_trak_opaque_box_qa70.py"
spec = importlib.util.spec_from_file_location("qa70_helpers_for_qa71", HELPERS)
assert spec and spec.loader
qa70 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa70)
qa62, qa58 = qa70.qa62, qa70.qa58
CANARY = b"QA71_SYNTHETIC_PRIVATE_CANARY"


def _inject_mdia_child(media: Path, workspace: Path, kind: bytes, *, empty: bool = False) -> None:
    # Remux to put moov AFTER mdat: growing mdia/trak/moov then leaves stco
    # chunk offsets unchanged, so both FFprobe and a full video decode work.
    remux = workspace / "qa71-end-moov.mp4"
    subprocess.run([
        qa58._require_ffmpeg(), "-nostdin", "-hide_banner", "-loglevel", "error",
        "-i", str(media), "-map", "0:v:0", "-c:v", "copy", "-y", str(remux),
    ], check=True, capture_output=True, timeout=60)
    data = remux.read_bytes()

    def find_box(start: int, end: int, wanted: bytes) -> tuple[int, int]:
        position = start
        while position < end:
            assert end - position >= 8
            size = int.from_bytes(data[position:position + 4], "big")
            assert size >= 8 and position + size <= end
            if data[position + 4:position + 8] == wanted:
                return position, size
            position += size
        raise AssertionError("required synthetic MP4 box not found")

    moov_pos, moov_size = find_box(0, len(data), b"moov")
    assert moov_pos + moov_size == len(data), "moov must follow media data"
    trak_pos, trak_size = find_box(moov_pos + 8, moov_pos + moov_size, b"trak")
    mdia_pos, mdia_size = find_box(trak_pos + 8, trak_pos + trak_size, b"mdia")
    payload = b"" if empty else (
        CANARY if kind == b"free" else b"0123456789ABCDEF" + CANARY
    )
    child = struct.pack(">I4s", 8 + len(payload), kind) + payload
    assert max(moov_size, trak_size, mdia_size) + len(child) < 2**32
    patched = (
        data[:mdia_pos]
        + struct.pack(">I", mdia_size + len(child))
        + data[mdia_pos + 4:mdia_pos + mdia_size]
        + child
        + data[mdia_pos + mdia_size:]
    )
    # Ancestor sizes change, but the media offsets do not.
    for position, size in ((trak_pos, trak_size), (moov_pos, moov_size)):
        patched = (
            patched[:position] + struct.pack(">I", size + len(child))
            + patched[position + 4:]
        )
    media.write_bytes(patched)
    remux.unlink()
    if not empty:
        assert CANARY in media.read_bytes()


@pytest.mark.parametrize("case,expected_pass", [
    ("clean", True),
    ("mdia_empty_free", True),
    ("mdia_free", False),
    ("mdia_uuid", False),
])
def test_strict_master_rejects_opaque_mdia_child(
    case, expected_pass, tmp_path, monkeypatch, capsys
):
    media, db, workspace = qa58._workspace(tmp_path)
    if case != "clean":
        _inject_mdia_child(
            media, workspace, b"uuid" if case == "mdia_uuid" else b"free",
            empty=case == "mdia_empty_free",
        )
    probe = json.loads(subprocess.run([
        "ffprobe", "-v", "error", "-show_entries",
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
    assert legacy["hash_attested_masters"] == 1
    strict_code, report = qa62._invoke(monkeypatch, capsys, workspace, db, True)
    assert strict_code == (0 if expected_pass else 1), (
        "strict inspector missed opaque payload inside moov/trak/mdia"
    )
    assert report["integrity_attestation_complete"] is expected_pass
    assert report["nested_mp4_payload_anomaly_count"] == (0 if expected_pass else 1)
    assert report["nested_mp4_payload_unattested_count"] == 0
    assert CANARY.decode() not in json.dumps(report)
    assert report["safe_to_delete_automatically"] is False
