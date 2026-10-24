"""Helper 1: loopback-only API access must not trust a rebinding Host/Origin.

Conditional in-process DNS-rebinding threat model. No DNS server, public tunnel,
real owner media, or actual browser exploit is used. Media proof is genuine
synthetic FFmpeg/FFprobe/full decode, not mocked FFmpeg.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient


def _tools():
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        if os.getenv("CINEMATIC_REQUIRE_REAL_MEDIA") == "1":
            pytest.fail("Strict rebinding QA requires real FFmpeg and FFprobe")
        pytest.skip("Real FFmpeg/FFprobe unavailable in ordinary CI")
    return ffmpeg, ffprobe


def _run(*args):
    return subprocess.run(args, check=True, capture_output=True, timeout=120)


def test_rebinding_host_and_matching_origin_cannot_mutate_local_studio_without_token(
    monkeypatch, tmp_path: Path,
):
    ffmpeg, ffprobe = _tools()
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("CHARACTER3D_STUDIO_TOKEN", raising=False)
    monkeypatch.setenv("CHARACTER3D_STUDIO_ORIGINS", "")

    storage = importlib.import_module("app.video.storage")
    service = importlib.import_module("app.video.cinematic_service")
    asset_id = "7" * 32
    source = storage.video_asset_path(asset_id, "mp4")
    _run(
        ffmpeg, "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=red:s=160x90:r=24:d=2",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(source),
    )
    payload = source.read_bytes()
    assert len(payload) > 2048
    digest = hashlib.sha256(payload).hexdigest()
    metadata = json.loads(_run(
        ffprobe, "-v", "error", "-count_frames", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,nb_read_frames",
        "-of", "json", str(source),
    ).stdout)
    assert metadata["streams"][0]["codec_name"] == "h264"
    assert int(metadata["streams"][0]["nb_read_frames"]) == 48
    _run(ffmpeg, "-nostdin", "-v", "error", "-xerror",
         "-i", str(source), "-an", "-f", "null", "-")
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest

    for name in ("app.studio.server", "app.video.router"):
        sys.modules.pop(name, None)
    server = importlib.import_module("app.studio.server")
    url = f"/api/video/assets/{asset_id}.mp4"
    project_request = {
        "title": "Synthetic origin/Host boundary QA",
        "master_prompt": "Synthetic only; no owner data",
        "target_duration_seconds": 10,
        "delivery_fps": 24,
        "delivery_resolution": "480p",
        "aspect_ratio": "16:9",
    }

    # Control: actual local access is supported without a configured token.
    with TestClient(server.app, base_url="http://localhost",
                    client=("127.0.0.1", 42000)) as local:
        media = local.get(url)
        assert media.status_code == 200
        assert media.headers["cache-control"] == "no-store"
        assert media.content == payload
        good = local.post(
            "/api/video/projects", json=project_request,
            headers={"Origin": "http://localhost"},
        )
        assert good.status_code == 200
    before = len(service.list_projects())

    # Control: a directly remote peer cannot write without a studio token.
    with TestClient(server.app, base_url="http://cinema.attacker.invalid",
                    client=("198.51.100.24", 42001)) as remote:
        denied = remote.post(
            "/api/video/projects", json=project_request,
            headers={"Origin": "http://cinema.attacker.invalid"},
        )
        assert denied.status_code == 403
    assert len(service.list_projects()) == before

    # Simulate a DNS-rebound hostname resolving to 127.0.0.1. A browser's
    # Origin and HTTP Host can both name the attacker-controlled hostname.
    # Comparing Origin against request.base_url is not a trusted-host check.
    with TestClient(server.app, base_url="http://cinema.attacker.invalid",
                    client=("127.0.0.1", 42002)) as rebound:
        response = rebound.post(
            "/api/video/projects", json=project_request,
            headers={"Origin": "http://cinema.attacker.invalid"},
        )
        assert response.status_code in (401, 403), (
            "An attacker-controlled Host with a matching Origin was accepted "
            "as a local owner and permitted to mutate a cinematic project"
        )
    assert len(service.list_projects()) == before
