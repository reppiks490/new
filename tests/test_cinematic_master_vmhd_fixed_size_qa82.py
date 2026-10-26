"""QA82: permitted MP4 vmhd FullBox must not hide opaque private suffixes.

Genuine disposable FFmpeg H.264; temporary SQLite; no owner media or inference.
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
    "qa81_helpers_for_qa82",
    ROOT / "tests" / "test_cinematic_master_track_media_header_size_qa81.py",
)
assert spec and spec.loader
qa81 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa81)
qa58, qa62 = qa81.qa58, qa81.qa62
CANARY = b"QA82_DISPOSABLE_VMHD_PRIVATE_CANARY"


def _inject_vmhd_suffix(media: Path, workspace: Path) -> None:
    """Insert canary inside the permitted vmhd box, correcting ancestor lengths.

    The moov-at-end remux avoids shifting mdat sample offsets; the media must
    remain fully decodable to isolate the strict privacy-integrity regression.
    """
    remux = workspace / "qa82-end-moov.mp4"
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
        raise AssertionError("missing expected synthetic FFmpeg MP4 box")

    chain = []
    start, end = 0, len(data)
    for kind in (b"moov", b"trak", b"mdia", b"minf", b"vmhd"):
        position, size = find_box(start, end, kind)
        chain.append((position, size))
        start, end = position + 8, position + size
    assert chain[0][0] + chain[0][1] == len(data)
    vmhd_position, vmhd_size = chain[-1]
    assert vmhd_size == 20  # ISO-BMFF vmhd: 8-byte box + 12-byte payload
    assert data[vmhd_position + 8:vmhd_position + 12] == bytes((0, 0, 0, 1))
    patched = data[:vmhd_position + vmhd_size] + CANARY + data[vmhd_position + vmhd_size:]
    for position, size in chain:
        patched = (
            patched[:position] + struct.pack(">I", size + len(CANARY))
            + patched[position + 4:]
        )
    media.write_bytes(patched)
    remux.unlink()
    assert CANARY in media.read_bytes()


@pytest.mark.parametrize("case", ["clean", "vmhd_suffix"])
def test_strict_audit_rejects_opaque_vmhd_suffix(case, tmp_path, monkeypatch, capsys):
    media, db, workspace = qa58._workspace(tmp_path)
    if case == "vmhd_suffix":
        _inject_vmhd_suffix(media, workspace)

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
    assert strict_code == (0 if clean else 1), "opaque vmhd suffix escaped strict audit"
    assert report["integrity_attestation_complete"] is clean
    assert report["nested_mp4_payload_anomaly_count"] == (0 if clean else 1)
    assert report["nested_mp4_payload_unattested_count"] == 0
    assert CANARY.decode() not in json.dumps(report)
    assert report["safe_to_delete_automatically"] is False
