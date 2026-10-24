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
        "master_prompt": "SYNTHETIC_PRIVATE_REBINDING_SCREENPLAY_f81d",
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
        project_id = good.json()["id"]
        assert good.json()["master_prompt"] == project_request["master_prompt"]
        assert local.get(f"/api/video/projects/{project_id}").json()[
            "master_prompt"
        ] == project_request["master_prompt"]
    before = len(service.list_projects())

    # Control: a genuinely remote peer cannot read private media or screenplay
    # and cannot write when no token is configured.
    private_routes = (
        ("project-list", "/api/video/projects"),
        ("project-detail", f"/api/video/projects/{project_id}"),
        ("private-mp4", url),
    )
    with TestClient(server.app, base_url="http://cinema.attacker.invalid",
                    client=("198.51.100.24", 42001)) as remote:
        for label, route in private_routes:
            denied_read = remote.get(route)
            assert denied_read.status_code == 403, label
        denied = remote.post(
            "/api/video/projects", json=project_request,
            headers={"Origin": "http://cinema.attacker.invalid"},
        )
        assert denied.status_code == 403
    assert len(service.list_projects()) == before

    # Conditional DNS-rebinding simulation: an attacker-owned Host and Origin
    # both name a domain resolved to loopback. Read and write access must be
    # denied, even if the peer IP appears local. Collect all outcomes rather
    # than failing on the first route so CI identifies each distinct exposure.
    # This is NOT proof of a real DNS/browser attack or deployed exposure.
    violations = []
    with TestClient(server.app, base_url="http://cinema.attacker.invalid",
                    client=("127.0.0.1", 42002)) as rebound:
        for label, route in private_routes:
            exposed = rebound.get(
                route, headers={"Origin": "http://cinema.attacker.invalid"},
            )
            assert exposed.request.headers["host"] == "cinema.attacker.invalid"
            if exposed.status_code not in (401, 403):
                violations.append(f"{label}:HTTP-{exposed.status_code}")
                # Establish the *synthetic* data really crossed the boundary,
                # not just that a handler returned an empty success response.
                if exposed.status_code == 200 and label == "private-mp4":
                    assert exposed.content == payload
                elif exposed.status_code == 200 and label == "project-detail":
                    assert exposed.json()["master_prompt"] == project_request[
                        "master_prompt"
                    ]
                elif exposed.status_code == 200 and label == "project-list":
                    assert any(
                        item.get("master_prompt") == project_request["master_prompt"]
                        for item in exposed.json()
                    )
        response = rebound.post(
            "/api/video/projects", json=project_request,
            headers={"Origin": "http://cinema.attacker.invalid"},
        )
        if response.status_code not in (401, 403):
            violations.append(f"project-write:HTTP-{response.status_code}")
    # Browser navigation GETs frequently omit Origin entirely. Host validation
    # must not depend on an Origin header being present. A non-browser client
    # can also send POST without Origin; reject that untrusted Host too.
    with TestClient(server.app, base_url="http://cinema.attacker.invalid",
                    client=("127.0.0.1", 42003)) as originless:
        for label, route in private_routes:
            exposed = originless.get(route)
            assert exposed.request.headers["host"] == "cinema.attacker.invalid"
            assert "origin" not in exposed.request.headers
            if exposed.status_code not in (401, 403):
                violations.append(f"originless-navigation-{label}:HTTP-{exposed.status_code}")
                if exposed.status_code == 200 and label == "private-mp4":
                    assert exposed.content == payload
                elif exposed.status_code == 200 and label == "project-detail":
                    assert exposed.json()["master_prompt"] == project_request["master_prompt"]
                elif exposed.status_code == 200 and label == "project-list":
                    assert any(
                        item.get("master_prompt") == project_request["master_prompt"]
                        for item in exposed.json()
                    )
        no_origin_write = originless.post("/api/video/projects", json=project_request)
        assert "origin" not in no_origin_write.request.headers
        if no_origin_write.status_code not in (401, 403):
            violations.append(f"originless-project-write:HTTP-{no_origin_write.status_code}")

    # A trusted-looking Origin must not override an untrusted Host. This is
    # an in-process header combination, not a claim of browser exploitability.
    with TestClient(server.app, base_url="http://cinema.attacker.invalid",
                    client=("127.0.0.1", 42004)) as spoofed:
        for label, route in private_routes:
            exposed = spoofed.get(route, headers={"Origin": "http://localhost"})
            assert exposed.request.headers["host"] == "cinema.attacker.invalid"
            if exposed.status_code not in (401, 403):
                violations.append(f"trusted-origin-untrusted-host-{label}:HTTP-{exposed.status_code}")
                if exposed.status_code == 200 and label == "private-mp4":
                    assert exposed.content == payload
                elif exposed.status_code == 200 and label == "project-detail":
                    assert exposed.json()["master_prompt"] == project_request["master_prompt"]
                elif exposed.status_code == 200 and label == "project-list":
                    assert any(
                        item.get("master_prompt") == project_request["master_prompt"]
                        for item in exposed.json()
                    )
        spoofed_write = spoofed.post(
            "/api/video/projects", json=project_request,
            headers={"Origin": "http://localhost"},
        )
        if spoofed_write.status_code not in (401, 403):
            violations.append(f"trusted-origin-untrusted-host-write:HTTP-{spoofed_write.status_code}")

    # Owner privacy controls are also private API state. A rebinding Host must
    # not read preferences or disable protections, even with a local TCP peer.
    # These are synthetic settings in tmp_path, never owner preferences.
    privacy_url = "/api/video/privacy"
    with TestClient(server.app, base_url="http://localhost",
                    client=("127.0.0.1", 42005)) as local:
        baseline_privacy = local.get(privacy_url)
        assert baseline_privacy.status_code == 200
        original_privacy = baseline_privacy.json()
        assert local.put(privacy_url, json=original_privacy).status_code == 200

    with TestClient(server.app, base_url="http://cinema.attacker.invalid",
                    client=("198.51.100.24", 42006)) as remote:
        assert remote.get(privacy_url).status_code == 403
        assert remote.put(privacy_url, json=original_privacy).status_code == 403

    changed_privacy = {
        **original_privacy,
        "privacy_mode": not original_privacy["privacy_mode"],
        "idle_lock_seconds": 77,
    }
    privacy_variants = (
        ("matching-attacker-origin", {"Origin": "http://cinema.attacker.invalid"}),
        ("originless", {}),
        ("trusted-looking-origin", {"Origin": "http://localhost"}),
    )
    for offset, (variant, headers) in enumerate(privacy_variants):
        with TestClient(server.app, base_url="http://cinema.attacker.invalid",
                        client=("127.0.0.1", 42010 + offset)) as rebound_privacy:
            exposed = rebound_privacy.get(privacy_url, headers=headers)
            assert exposed.request.headers["host"] == "cinema.attacker.invalid"
            if exposed.status_code not in (401, 403):
                violations.append(f"{variant}-privacy-read:HTTP-{exposed.status_code}")
                if exposed.status_code == 200:
                    assert "privacy_mode" in exposed.json()
                    assert "idle_lock_seconds" in exposed.json()
            modified = rebound_privacy.put(
                privacy_url, headers=headers, json=changed_privacy,
            )
            if modified.status_code not in (401, 403):
                violations.append(f"{variant}-privacy-write:HTTP-{modified.status_code}")
                if modified.status_code == 200:
                    assert modified.json()["privacy_mode"] == changed_privacy["privacy_mode"]
                    assert modified.json()["idle_lock_seconds"] == 77

    with TestClient(server.app, base_url="http://localhost",
                    client=("127.0.0.1", 42020)) as local:
        if local.get(privacy_url).json() != original_privacy:
            violations.append("unauthorized-privacy-preferences-mutation")

    if len(service.list_projects()) != before:
        violations.append("unauthorized-project-mutation")
    assert not violations, (
        "Tokenless DNS-rebound Host/Origin accepted private synthetic media, "
        "screenplay or writes: " + ", ".join(violations)
    )
