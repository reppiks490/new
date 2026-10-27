"""QA106: fail closed on undecodable local FFmpeg/FFprobe metadata.

Mock-only regression: no owner media, binaries, rendering, network, or cloud use.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from app.video import cinematic_local_media_preflight_qa105 as preflight


_PRIVATE = "OWNER_PRIVATE_TOOLCHAIN_PATH"


def _decode_failure():
    payload = _PRIVATE.encode("ascii") + b"\xff"
    return UnicodeDecodeError("utf-8", payload, len(payload) - 1, len(payload), "invalid byte")


@pytest.mark.parametrize(
    ("failing_probe", "blocked_check"),
    [
        ("ffmpeg-version", "ffmpeg_binary"),
        ("ffmpeg-encoders", "h264_encoder"),
        ("ffprobe-version", "ffprobe_binary"),
    ],
)
def test_undecodable_tool_output_fails_closed_without_exposing_bytes(
    monkeypatch, failing_probe, blocked_check,
):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/synthetic/" + name)

    def fake_run(argv, **kwargs):
        phase = (
            ("ffprobe" if "ffprobe" in argv[0] else "ffmpeg")
            + ("-encoders" if argv[-1] == "-encoders" else "-version")
        )
        if phase == failing_probe:
            raise _decode_failure()
        stdout = (
            " V....D libx264 H264 encoder\n"
            if argv[-1] == "-encoders"
            else "synthetic version"
        )
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(preflight.subprocess, "run", fake_run)
    report = preflight.audit_local_media_runtime(workspace=None)
    statuses = {item["name"]: item["status"] for item in report["checks"]}
    assert statuses[blocked_check] == "blocked"
    if failing_probe == "ffmpeg-version":
        assert statuses["h264_encoder"] == "not_checked"
    assert report["limited_ready"] is False
    assert report["release_ready"] is False
    assert _PRIVATE not in json.dumps(report)


def test_undecodable_binary_lookup_is_a_safe_blocker(monkeypatch):
    def bad_which(binary):
        if binary == "ffmpeg":
            raise UnicodeError(_PRIVATE)
        return "/synthetic/ffprobe"

    monkeypatch.setattr(preflight.shutil, "which", bad_which)
    monkeypatch.setattr(
        preflight.subprocess, "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, "synthetic version", ""),
    )
    report = preflight.audit_local_media_runtime(workspace=None)
    statuses = {item["name"]: item["status"] for item in report["checks"]}
    assert statuses["ffmpeg_binary"] == "blocked"
    assert statuses["h264_encoder"] == "not_checked"
    assert report["limited_ready"] is False
    assert _PRIVATE not in json.dumps(report)


def test_cli_does_not_emit_traceback_or_private_decoder_bytes(monkeypatch, capsys):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/synthetic/" + name)
    monkeypatch.setattr(
        preflight.subprocess, "run",
        lambda argv, **kwargs: (_ for _ in ()).throw(_decode_failure()),
    )
    assert preflight.main([]) == 2
    captured = capsys.readouterr()
    assert captured.err == ""
    assert _PRIVATE not in captured.out
    report = json.loads(captured.out)
    assert report["limited_ready"] is False
    assert report["release_ready"] is False
