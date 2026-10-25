"""QA66: an otherwise valid master can carry private free-form MP4 payloads.

All footage and canaries are disposable synthetic FFmpeg/SQLite fixtures.
This is NOT a claim about actual owner media, phones, or model inference.
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
spec = importlib.util.spec_from_file_location("qa62_helpers_for_qa66", HELPERS)
assert spec and spec.loader
qa62 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa62)
qa58 = qa62.qa58

CANARY = "SYNTHETIC_QA66_PRIVATE_PAYLOAD_CANARY"


@pytest.mark.parametrize("case,expected_pass", [
    ("clean", True),
    ("freeform_comment", False),
    ("subtitle_track", False),
    ("chapter_title", False),
])
def test_strict_master_rejects_private_auxiliary_payloads(
    case, expected_pass, tmp_path, monkeypatch, capsys
):
    media, db, workspace = qa58._workspace(tmp_path)
    if case != "clean":
        replacement = workspace / "qa66-synthetic-remux.mp4"
        ffmpeg = qa58._require_ffmpeg()
        cmd = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
               "-i", str(media)]
        if case == "freeform_comment":
            cmd += ["-map", "0:v:0", "-c:v", "copy",
                    "-metadata", "comment=" + CANARY]
        elif case == "subtitle_track":
            subtitle = workspace / "qa66-synthetic.srt"
            subtitle.write_text(
                "1\n00:00:00,500 --> 00:00:01,500\n" + CANARY + "\n",
                encoding="utf-8",
            )
            cmd += ["-f", "srt", "-i", str(subtitle),
                    "-map", "0:v:0", "-map", "1:s:0",
                    "-c:v", "copy", "-c:s", "mov_text"]
        else:
            chapters = workspace / "qa66-synthetic.ffmeta"
            chapters.write_text(
                ";FFMETADATA1\n[CHAPTER]\nTIMEBASE=1/1000\n"
                "START=0\nEND=1000\ntitle=" + CANARY + "\n",
                encoding="utf-8",
            )
            cmd += ["-f", "ffmetadata", "-i", str(chapters),
                    "-map", "0:v:0", "-map_metadata", "0",
                    "-map_chapters", "1", "-c:v", "copy"]
        cmd += ["-movflags", "+faststart", "-y", str(replacement)]
        subprocess.run(cmd, check=True, capture_output=True, timeout=60)
        os.replace(replacement, media)

    details = json.loads(subprocess.run([
        "ffprobe", "-v", "error",
        "-show_entries",
        "stream=codec_type,codec_name,nb_frames:format=duration:"
        "format_tags:chapter=start_time,end_time:chapter_tags",
        "-of", "json", str(media),
    ], check=True, capture_output=True, timeout=60).stdout)
    videos = [s for s in details["streams"] if s.get("codec_type") == "video"]
    assert len(videos) == 1
    assert videos[0]["codec_name"] == "h264"
    assert videos[0]["nb_frames"] == "48"
    assert abs(float(details["format"]["duration"]) - 2.0) < 0.05
    if case == "freeform_comment":
        assert details["format"]["tags"]["comment"] == CANARY
    elif case == "subtitle_track":
        assert any(s.get("codec_type") == "subtitle" for s in details["streams"])
    elif case == "chapter_title":
        assert any(c.get("tags", {}).get("title") == CANARY
                   for c in details.get("chapters", []))

    # Video decodes fully, regardless of private auxiliary payload.
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
        "Correct video/SHA/timing must not attest a private auxiliary MP4 payload"
    )
    assert report["integrity_attestation_complete"] is expected_pass
    assert report["auxiliary_stream_anomaly_count"] == (
        1 if case in ("subtitle_track", "chapter_title") else 0
    )
    assert report["freeform_metadata_anomaly_count"] == (
        1 if case == "freeform_comment" else 0
    )
    assert report["chapter_anomaly_count"] == (
        1 if case == "chapter_title" else 0
    )
    assert CANARY not in json.dumps(report)
    assert report["safe_to_delete_automatically"] is False
