"""QA108: local preflight must not accept unrelated exit-zero executables.

These are mocked toolchain metadata responses. No media, cloud services, owner
paths, actual model inference or encoding are involved.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from app.video import cinematic_local_media_preflight_qa105 as preflight


@pytest.mark.parametrize("fake_version", ["", "unrelated tool version 1.0", "ffprobe version 7.0"])
def test_ffmpeg_exit_zero_wrong_identity_fails_closed(monkeypatch, tmp_path, fake_version):
    calls = []
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/synthetic/" + name)

    def run(argv, **kwargs):
        calls.append(tuple(argv))
        assert kwargs["timeout"] <= 8
        if argv[-1] == "-version":
            output = fake_version if argv[0].endswith("ffmpeg") else "ffprobe version 7.0"
        else:
            output = " V....D libx264 H.264 encoder\n"
        return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="PRIVATE_DIAGNOSTIC")

    monkeypatch.setattr(preflight.subprocess, "run", run)
    monkeypatch.setattr(preflight.shutil, "disk_usage", lambda path: type("Usage", (), {"free": 20 * 1024**3})())
    report = preflight.audit_local_media_runtime(workspace=tmp_path)
    statuses = {item["name"]: item for item in report["checks"]}
    assert statuses["ffmpeg_binary"]["status"] == "blocked"
    assert statuses["h264_encoder"]["status"] == "not_checked"
    assert not any(argv[-1] == "-encoders" for argv in calls)
    assert report["limited_ready"] is False
    assert report["release_ready"] is False
    assert "PRIVATE_DIAGNOSTIC" not in json.dumps(report)


@pytest.mark.parametrize("fake_version", ["", "unrelated tool version 1.0", "ffmpeg version 7.0"])
def test_ffprobe_exit_zero_wrong_identity_fails_closed(monkeypatch, fake_version):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/synthetic/" + name)

    def run(argv, **kwargs):
        if argv[-1] == "-version":
            output = fake_version if argv[0].endswith("ffprobe") else "ffmpeg version 7.0"
        else:
            output = " V....D libx264 H.264 encoder\n"
        return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="PRIVATE_DIAGNOSTIC")

    monkeypatch.setattr(preflight.subprocess, "run", run)
    report = preflight.audit_local_media_runtime(workspace=None)
    statuses = {item["name"]: item for item in report["checks"]}
    assert statuses["ffprobe_binary"]["status"] == "blocked"
    assert report["limited_ready"] is False
    assert report["release_ready"] is False
    assert "PRIVATE_DIAGNOSTIC" not in json.dumps(report)


def test_expected_ffmpeg_ffprobe_version_banners_remain_accepted(monkeypatch, tmp_path):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/synthetic/" + name)

    def run(argv, **kwargs):
        if argv[-1] == "-version":
            output = ("ffmpeg" if argv[0].endswith("ffmpeg") else "ffprobe") + " version 7.0 Copyright ..."
        else:
            output = " V....D libx264 H.264 encoder\n"
        return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")

    monkeypatch.setattr(preflight.subprocess, "run", run)
    monkeypatch.setattr(preflight.shutil, "disk_usage", lambda path: type("Usage", (), {"free": 20 * 1024**3})())
    report = preflight.audit_local_media_runtime(workspace=tmp_path)
    assert report["limited_ready"] is True
    assert report["release_ready"] is False
