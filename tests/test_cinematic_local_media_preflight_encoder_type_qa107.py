"""QA107: FFmpeg encoder type must be video, not merely a matching name.

All listings are synthetic. No FFmpeg process, owner media, workspace writes,
cloud generation, or actual model inference is exercised by these tests.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from app.video import cinematic_local_media_preflight_qa105 as preflight


@pytest.mark.parametrize("flags", ["A.....", "S.....", "......"])
def test_nonvideo_libx264_name_does_not_count_as_h264_video_encoder(flags):
    listing = (
        "Encoders:\n"
        " V..... mpeg4 MPEG-4 video\n"
        f" {flags} libx264 synthetic nonvideo encoder\n"
    )
    assert preflight._has_libx264_encoder(listing) is False


@pytest.mark.parametrize("flags", ["V....D", "V....."])
def test_genuine_video_type_flag_with_exact_libx264_name_is_accepted(flags):
    assert preflight._has_libx264_encoder(
        f" {flags} libx264 H.264 video encoder\n"
        " V....D libx264rgb another encoder\n"
    ) is True


def test_readiness_report_fails_closed_on_audio_only_libx264_listing(monkeypatch):
    private = "PRIVATE_SYNTHETIC_TOOLCHAIN_SENTINEL"
    monkeypatch.setattr(preflight.shutil, "which", lambda binary: "/synthetic/" + binary)

    def fake_run(argv, **kwargs):
        assert kwargs["capture_output"] is True
        assert kwargs["timeout"] <= 8
        if argv[-1] == "-encoders":
            output = f" A..... libx264 {private}\n V....D libx264rgb RGB only\n"
        else:
            output = "synthetic version"
        return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")

    monkeypatch.setattr(preflight.subprocess, "run", fake_run)
    report = preflight.audit_local_media_runtime(workspace=None)
    statuses = {item["name"]: item for item in report["checks"]}
    assert statuses["ffmpeg_binary"]["status"] == "passed"
    assert statuses["ffprobe_binary"]["status"] == "passed"
    assert statuses["h264_encoder"] == {
        "name": "h264_encoder", "status": "blocked", "code": "LIBX264_UNAVAILABLE"
    }
    assert report["limited_ready"] is False
    assert report["release_ready"] is False
    assert private not in json.dumps(report)
