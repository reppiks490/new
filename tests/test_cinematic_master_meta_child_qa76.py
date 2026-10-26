"""QA76: allowed udta/meta box can conceal unreported private payloads.

Only disposable synthetic FFmpeg H.264, full FFmpeg decode, FFprobe and a
temporary SQLite hash. No owner media, inference, mobile or cloud claims.
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
HELPERS = ROOT / "tests" / "test_cinematic_master_allowed_container_qa75.py"
spec = importlib.util.spec_from_file_location("qa75_helpers_for_qa76", HELPERS)
assert spec and spec.loader
qa75 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa75)
qa58, qa62 = qa75.qa58, qa75.qa62
CANARY = b"QA76_DISPOSABLE_META_CHILD_PRIVATE_CANARY"


def _inject_meta_child(media: Path, workspace: Path) -> None:
    # An EOF moov permits insertion without moving mdat/chunk offsets.
    remux = workspace / "qa76-end-moov.mp4"
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
            assert size >= 8 and cursor + size <= end
            if data[cursor + 4:cursor + 8] == wanted:
                return cursor, size
            cursor += size
        raise AssertionError("expected synthetic FFmpeg metadata container missing")

    chain = []
    start, end = 0, len(data)
    for kind in (b"moov", b"udta", b"meta"):
        position, size = find_box(start, end, kind)
        chain.append((position, size))
        start, end = position + (12 if kind == b"meta" else 8), position + size
    assert chain[0][0] + chain[0][1] == len(data)
    child = struct.pack(">I4s", 8 + len(CANARY), b"priv") + CANARY
    assert all(size + len(child) < 2**32 for _, size in chain)
    insert_at = chain[-1][0] + chain[-1][1]
    patched = data[:insert_at] + child + data[insert_at:]
    for position, size in chain:
        patched = patched[:position] + struct.pack(">I", size + len(child)) + patched[position + 4:]
    media.write_bytes(patched)
    remux.unlink()
    assert CANARY in media.read_bytes()


@pytest.mark.parametrize("case", ["clean", "udta_meta_private_child"])
def test_meta_nested_private_payload_must_fail_strict_integrity(
    case, tmp_path, monkeypatch, capsys
):
    media, db, workspace = qa58._workspace(tmp_path)
    if case != "clean":
        _inject_meta_child(media, workspace)

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
    assert decoded.returncode == 0, "synthetic MP4 must fully decode"

    qa58._record(db, 1, hashlib.sha256(media.read_bytes()).hexdigest())
    legacy_code, legacy = qa62._invoke(monkeypatch, capsys, workspace, db, False)
    assert legacy_code == 0
    assert legacy["verified_decodable_masters"] == 1
    assert legacy["hash_attested_masters"] == 1

    strict_code, report = qa62._invoke(monkeypatch, capsys, workspace, db, True)
    clean = case == "clean"
    assert strict_code == (0 if clean else 1), "opaque meta child escaped strict audit"
    assert report["integrity_attestation_complete"] is clean
    assert report["nested_mp4_payload_anomaly_count"] == (0 if clean else 1)
    assert report["nested_mp4_payload_unattested_count"] == 0
    assert CANARY.decode() not in json.dumps(report)
    assert report["safe_to_delete_automatically"] is False
