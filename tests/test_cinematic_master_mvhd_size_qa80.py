"""QA80: opaque suffix in otherwise allowed ISO-BMFF movie header (mvhd).

Disposable real FFmpeg H.264 only; temporary SQLite, no owner media or inference.
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
    "qa79_helpers_for_qa80",
    ROOT / "tests" / "test_cinematic_master_encoder_data_length_qa79.py",
)
assert spec and spec.loader
qa79 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa79)
qa58, qa62 = qa79.qa58, qa79.qa62
CANARY = b"QA80_DISPOSABLE_MVHD_PRIVATE_CANARY"


def _inject_mvhd_suffix(media: Path, workspace: Path) -> None:
    # Keep moov after mdat so changing its length cannot shift chunk offsets.
    remux = workspace / "qa80-end-moov.mp4"
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
        raise AssertionError(f"missing expected synthetic FFmpeg box {wanted!r}")

    moov_pos, moov_size = find_box(0, len(data), b"moov")
    assert moov_pos + moov_size == len(data)
    mvhd_pos, mvhd_size = find_box(moov_pos + 8, moov_pos + moov_size, b"mvhd")
    assert data[mvhd_pos + 8] in (0, 1)
    # A legal movie header has a fixed version-dependent size; append bytes
    # inside its declared box, not as a new unknown child or top-level box.
    insert_at = mvhd_pos + mvhd_size
    patched = data[:insert_at] + CANARY + data[insert_at:]
    for position, size in ((mvhd_pos, mvhd_size), (moov_pos, moov_size)):
        assert size + len(CANARY) < 2**32
        patched = patched[:position] + struct.pack(">I", size + len(CANARY)) + patched[position + 4:]
    media.write_bytes(patched)
    remux.unlink()
    assert CANARY in media.read_bytes()


@pytest.mark.parametrize("case", ["clean", "mvhd_opaque_suffix"])
def test_strict_master_rejects_opaque_mvhd_suffix(
    case, tmp_path, monkeypatch, capsys
):
    media, db, workspace = qa58._workspace(tmp_path)
    if case != "clean":
        _inject_mvhd_suffix(media, workspace)

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
    assert strict_code == (0 if clean else 1), "opaque mvhd suffix escaped strict audit"
    assert report["integrity_attestation_complete"] is clean
    assert report["nested_mp4_payload_anomaly_count"] == (0 if clean else 1)
    assert report["nested_mp4_payload_unattested_count"] == 0
    assert CANARY.decode() not in json.dumps(report)
    assert report["safe_to_delete_automatically"] is False
