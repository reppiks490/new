"""QA84: unknown MP4 data-information children must not pass strict privacy audit.

Genuine disposable FFmpeg H.264 media, full decode and temporary SQLite only.
No owner footage, credentials, external inference or production file mutation.
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
    "qa83_helpers_for_qa84", ROOT / "tests" / "test_cinematic_master_hdlr_suffix_qa83.py"
)
assert spec and spec.loader
qa83 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa83)
qa58, qa62 = qa83.qa58, qa83.qa62
CANARY = b"QA84_DISPOSABLE_DINF_PRIVATE_CANARY"


def _inject_unknown_dinf_child(media: Path, workspace: Path) -> None:
    """Append an opaque sibling of dref inside dinf; keep mdat offsets stable."""
    remux = workspace / "qa84-end-moov.mp4"
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
        raise AssertionError("missing synthetic FFmpeg MP4 box")

    chain = []
    start, end = 0, len(data)
    for kind in (b"moov", b"trak", b"mdia", b"minf", b"dinf"):
        position, size = find_box(start, end, kind)
        chain.append((position, size))
        start, end = position + 8, position + size
    assert chain[0][0] + chain[0][1] == len(data), "moov must follow mdat"
    dinf_position, dinf_size = chain[-1]
    assert find_box(dinf_position + 8, dinf_position + dinf_size, b"dref")

    unknown = struct.pack(">I4s", 8 + len(CANARY), b"priv") + CANARY
    insert_at = dinf_position + dinf_size
    patched = data[:insert_at] + unknown + data[insert_at:]
    for box_position, box_size in chain:
        patched = (
            patched[:box_position]
            + struct.pack(">I", box_size + len(unknown))
            + patched[box_position + 4:]
        )
    media.write_bytes(patched)
    remux.unlink()
    assert CANARY in media.read_bytes()


@pytest.mark.parametrize("case", ["clean", "unknown_dinf_child"])
def test_strict_audit_rejects_hidden_dinf_child(case, tmp_path, monkeypatch, capsys):
    media, db, workspace = qa58._workspace(tmp_path)
    if case == "unknown_dinf_child":
        _inject_unknown_dinf_child(media, workspace)

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
    assert strict_code == (0 if clean else 1), "opaque dinf child escaped strict audit"
    assert report["integrity_attestation_complete"] is clean
    assert report["nested_mp4_payload_anomaly_count"] == (0 if clean else 1)
    assert report["nested_mp4_payload_unattested_count"] == 0
    assert CANARY.decode() not in json.dumps(report)
    assert report["safe_to_delete_automatically"] is False
