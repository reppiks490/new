"""QA74: unknown nested MP4 box types must not pass strict private-master audit.

Disposable FFmpeg H.264, FFprobe, full decode and temporary SQLite SHA only.
No owner media, model inference, phone playback or cloud generation.
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
HELPERS = ROOT / "tests" / "test_cinematic_master_stbl_opaque_box_qa73.py"
spec = importlib.util.spec_from_file_location("qa73_helpers_for_qa74", HELPERS)
assert spec and spec.loader
qa73 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa73)
qa58, qa62 = qa73.qa58, qa73.qa62
CANARY = b"QA74_SYNTHETIC_UNKNOWN_BOX_PRIVATE_CANARY"
LEVELS = ("moov", "trak", "mdia", "minf", "stbl")


def _inject_unknown_child(media: Path, workspace: Path, level: str) -> None:
    # End-of-file moov keeps mdat chunk offsets valid while inserting a child.
    remux = workspace / "qa74-end-moov.mp4"
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
        raise AssertionError("synthetic MP4 parent box missing")

    chain = []
    start, end = 0, len(data)
    for name in LEVELS[:LEVELS.index(level) + 1]:
        position, size = find_box(start, end, name.encode("ascii"))
        chain.append((position, size))
        start, end = position + 8, position + size
    assert chain[0][0] + chain[0][1] == len(data)
    child = struct.pack(">I4s", 8 + len(CANARY), b"priv") + CANARY
    assert all(size + len(child) < 2**32 for _, size in chain)
    insert_at = chain[-1][0] + chain[-1][1]
    patched = data[:insert_at] + child + data[insert_at:]
    for position, size in chain:
        patched = (
            patched[:position] + struct.pack(">I", size + len(child))
            + patched[position + 4:]
        )
    media.write_bytes(patched)
    remux.unlink()
    assert CANARY in media.read_bytes()


@pytest.mark.parametrize("level", ["clean", *LEVELS])
def test_unknown_nested_mp4_child_fails_strict_privacy(
    level, tmp_path, monkeypatch, capsys
):
    media, db, workspace = qa58._workspace(tmp_path)
    if level != "clean":
        _inject_unknown_child(media, workspace, level)
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
    assert decoded.returncode == 0, "synthetic fixture must decode completely"

    qa58._record(db, 1, hashlib.sha256(media.read_bytes()).hexdigest())
    legacy_code, legacy = qa62._invoke(monkeypatch, capsys, workspace, db, False)
    assert legacy_code == 0
    assert legacy["verified_decodable_masters"] == 1
    assert legacy["hash_attested_masters"] == 1
    strict_code, report = qa62._invoke(monkeypatch, capsys, workspace, db, True)
    expected_pass = level == "clean"
    assert strict_code == (0 if expected_pass else 1), (
        "unknown nested MP4 box escaped strict privacy attestation at " + level
    )
    assert report["integrity_attestation_complete"] is expected_pass
    assert report["nested_mp4_payload_anomaly_count"] == (0 if expected_pass else 1)
    assert report["nested_mp4_payload_unattested_count"] == 0
    assert CANARY.decode() not in json.dumps(report)
    assert report["safe_to_delete_automatically"] is False
