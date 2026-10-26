"""QA78: hidden opaque child inside an allowed FFmpeg encoder metadata item.

Only disposable synthetic FFmpeg H.264, temporary SQLite and offline inspector.
No owner media, actual inference, cloud generation or physical mobile verification.
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
    "qa77_helpers_for_qa78", ROOT / "tests" / "test_cinematic_master_ilst_privacy_qa77.py"
)
assert spec and spec.loader
qa77 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa77)
qa58, qa62 = qa77.qa58, qa77.qa62
CANARY = b"QA78_DISPOSABLE_ENCODER_CHILD_PRIVATE_CANARY"


def _inject_private_encoder_child(media: Path, workspace: Path) -> None:
    # Remux with moov at EOF so adding metadata never shifts mdat offsets.
    remux = workspace / "qa78-end-moov.mp4"
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
    for kind in (b"moov", b"udta", b"meta", b"ilst", b"\xa9too"):
        position, size = find_box(start, end, kind)
        chain.append((position, size))
        start = position + (12 if kind == b"meta" else 8)
        end = position + size
    assert chain[0][0] + chain[0][1] == len(data)
    item_pos, item_size = chain[-1]
    # An allowed encoder item already contains its legitimate 'data' child.
    data_pos, data_size = find_box(item_pos + 8, item_pos + item_size, b"data")
    assert data_pos + data_size <= item_pos + item_size
    child = struct.pack(">I4s", 8 + len(CANARY), b"priv") + CANARY
    assert all(size + len(child) < 2**32 for _, size in chain)
    insert_at = item_pos + item_size
    patched = data[:insert_at] + child + data[insert_at:]
    for position, size in chain:
        patched = patched[:position] + struct.pack(">I", size + len(child)) + patched[position + 4:]
    media.write_bytes(patched)
    remux.unlink()
    assert CANARY in media.read_bytes()


@pytest.mark.parametrize("case", ["clean", "encoder_private_child"])
def test_allowed_encoder_item_cannot_hide_opaque_child(case, tmp_path, monkeypatch, capsys):
    media, db, workspace = qa58._workspace(tmp_path)
    if case != "clean":
        _inject_private_encoder_child(media, workspace)

    probe = json.loads(subprocess.run([
        "ffprobe", "-v", "error", "-show_entries",
        "stream=codec_type,codec_name,nb_frames:stream_tags:"
        "format=duration:format_tags:chapter=start_time,end_time:chapter_tags",
        "-of", "json", str(media),
    ], check=True, capture_output=True, timeout=60).stdout)
    videos = [s for s in probe["streams"] if s.get("codec_type") == "video"]
    assert len(videos) == 1 and videos[0]["codec_name"] == "h264"
    assert videos[0]["nb_frames"] == "48"
    assert abs(float(probe["format"]["duration"]) - 2) < 0.05
    assert CANARY.decode() not in json.dumps(probe)

    decoded = subprocess.run([
        qa58._require_ffmpeg(), "-nostdin", "-hide_banner", "-v", "error",
        "-xerror", "-protocol_whitelist", "file", "-i", str(media),
        "-map", "0:v:0", "-an", "-f", "null", "-",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=60)
    assert decoded.returncode == 0, "synthetic media must fully decode"

    qa58._record(db, 1, hashlib.sha256(media.read_bytes()).hexdigest())
    legacy_code, legacy = qa62._invoke(monkeypatch, capsys, workspace, db, False)
    assert legacy_code == 0
    assert legacy["verified_decodable_masters"] == 1
    assert legacy["hash_attested_masters"] == 1

    strict_code, report = qa62._invoke(monkeypatch, capsys, workspace, db, True)
    clean = case == "clean"
    assert strict_code == (0 if clean else 1), "opaque encoder-item child escaped strict audit"
    assert report["integrity_attestation_complete"] is clean
    assert report["nested_mp4_payload_anomaly_count"] == (0 if clean else 1)
    assert report["nested_mp4_payload_unattested_count"] == 0
    assert CANARY.decode() not in json.dumps(report)
    assert report["safe_to_delete_automatically"] is False
