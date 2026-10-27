"""QA105: bounded, read-only local FFmpeg/FFprobe/disk readiness checks.

All media and workspace paths are synthetic. No owner files, model inference,
rendering, network calls or media writes are used by these unit tests.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from app.video import cinematic_local_media_preflight_qa105 as preflight


def _fake_environment(monkeypatch, *, codec=True, version=True, free_gib=24):
    calls = []

    def which(binary):
        return "/synthetic/toolchain/" + binary

    def run(args, **kwargs):
        calls.append(tuple(args))
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["timeout"] <= 10
        assert kwargs["check"] is False
        if args[-1] == "-version":
            return subprocess.CompletedProcess(args, 0 if version else 1, stdout=("ffprobe" if args[0].endswith("ffprobe") else "ffmpeg") + " version 7.0 synthetic", stderr="")
        assert args[-2:] == ["-hide_banner", "-encoders"]
        encoder_lines = " V....D libx264             H.264 synthetic encoder\n" if codec else " V....D mpeg4              MPEG4\n"
        return subprocess.CompletedProcess(args, 0, stdout=encoder_lines, stderr="")

    class Usage:
        free = free_gib * 1024 ** 3
        total = 64 * 1024 ** 3
        used = total - free

    monkeypatch.setattr(preflight.shutil, "which", which)
    monkeypatch.setattr(preflight.subprocess, "run", run)
    monkeypatch.setattr(preflight.shutil, "disk_usage", lambda path: Usage())
    return calls


def _statuses(report):
    return {check["name"]: (check["status"], check["code"]) for check in report["checks"]}


def test_all_limited_checks_pass_without_claiming_render_or_phone_ready(monkeypatch, tmp_path):
    calls = _fake_environment(monkeypatch)
    before = tuple(tmp_path.iterdir())
    report = preflight.audit_local_media_runtime(workspace=tmp_path, min_free_gib=10)
    assert report["limited_ready"] is True
    assert report["release_ready"] is False
    assert _statuses(report) == {
        "ffmpeg_binary": ("passed", "FFMPEG_RESPONSIVE"),
        "ffprobe_binary": ("passed", "FFPROBE_RESPONSIVE"),
        "h264_encoder": ("passed", "LIBX264_AVAILABLE"),
        "workspace_disk": ("passed", "WORKSPACE_FREE_SPACE_ABOVE_FLOOR"),
    }
    assert len(calls) == 3
    assert tuple(tmp_path.iterdir()) == before
    assert "MODEL_INFERENCE_NOT_TESTED" in report["not_verified"]
    assert "PHYSICAL_MOBILE_PLAYBACK_NOT_TESTED" in report["not_verified"]
    assert "MULTIPROCESS_QUEUE_NOT_SAFE" in report["not_verified"]


def test_missing_workspace_fails_closed_as_not_checked(monkeypatch):
    _fake_environment(monkeypatch)
    report = preflight.audit_local_media_runtime(workspace=None)
    assert not report["limited_ready"]
    assert _statuses(report)["workspace_disk"] == ("not_checked", "WORKSPACE_NOT_SUPPLIED")


def test_nonexistent_workspace_is_blocked_not_created(monkeypatch, tmp_path):
    _fake_environment(monkeypatch)
    missing = tmp_path / "private-do-not-create"
    report = preflight.audit_local_media_runtime(workspace=missing)
    assert not report["limited_ready"]
    assert _statuses(report)["workspace_disk"] == ("blocked", "WORKSPACE_NOT_DIRECTORY")
    assert not missing.exists()


def test_low_disk_and_missing_encoder_are_both_reported(monkeypatch, tmp_path):
    _fake_environment(monkeypatch, codec=False, free_gib=3)
    report = preflight.audit_local_media_runtime(workspace=tmp_path, min_free_gib=10)
    assert not report["limited_ready"]
    assert _statuses(report)["h264_encoder"] == ("blocked", "LIBX264_UNAVAILABLE")
    assert _statuses(report)["workspace_disk"] == ("blocked", "WORKSPACE_FREE_SPACE_BELOW_FLOOR")


def test_binary_failure_does_not_echo_private_executable_path(monkeypatch, tmp_path):
    _fake_environment(monkeypatch, version=False)
    secret = "/private/owner/MEDIA-SECRET/ffmpeg"
    report = preflight.audit_local_media_runtime(workspace=tmp_path, ffmpeg=secret)
    assert not report["limited_ready"]
    assert _statuses(report)["ffmpeg_binary"] == ("blocked", "FFMPEG_UNRESPONSIVE")
    assert _statuses(report)["h264_encoder"] == ("not_checked", "FFMPEG_NOT_VERIFIED")
    assert secret not in json.dumps(report)
    assert "MEDIA-SECRET" not in json.dumps(report)


def test_untrusted_subprocess_stderr_and_workspace_path_are_never_returned(monkeypatch, tmp_path):
    _fake_environment(monkeypatch)
    secret = "SECRET_OWNER_CREDENTIAL_DO_NOT_PRINT"
    def raise_secret(args, **kwargs):
        raise OSError(secret)
    monkeypatch.setattr(preflight.subprocess, "run", raise_secret)
    report = preflight.audit_local_media_runtime(workspace=tmp_path / secret)
    serialized = json.dumps(report)
    assert secret not in serialized
    assert report["limited_ready"] is False


@pytest.mark.parametrize("minimum", [0, -1, 1.5, True, "10"])
def test_invalid_disk_floor_is_rejected(minimum):
    with pytest.raises(ValueError):
        preflight.audit_local_media_runtime(workspace=None, min_free_gib=minimum)
