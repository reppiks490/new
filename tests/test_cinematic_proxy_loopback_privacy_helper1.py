"""Helper 1: a loopback reverse proxy must not turn remote viewers into local owners.

This is a conditional deployment privacy contract, not evidence that a real
reverse proxy is exposed. All media is synthetic, encoded with actual FFmpeg,
verified with FFprobe, fully decoded, and SHA-256 checked.
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


def _media_tools():
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        if os.getenv("CINEMATIC_REQUIRE_REAL_MEDIA") == "1":
            pytest.fail("Strict reverse-proxy privacy QA requires FFmpeg and FFprobe")
        pytest.skip("FFmpeg/FFprobe absent from ordinary CI")
    return ffmpeg, ffprobe


def _run(*command):
    return subprocess.run(command, check=True, capture_output=True, timeout=120)


def test_forwarded_remote_cannot_download_private_master_without_owner_token(
    monkeypatch, tmp_path: Path,
):
    ffmpeg, ffprobe = _media_tools()
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("CHARACTER3D_STUDIO_TOKEN", raising=False)
    monkeypatch.setenv("CHARACTER3D_STUDIO_ORIGINS", "")

    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    storage = importlib.import_module("app.video.storage")
    requests = importlib.import_module("app.video.cinematic_requests")

    project = service.create_project(models.ProjectCreateRequest(
        title="Synthetic proxy privacy QA", master_prompt="Synthetic test only",
        target_duration_seconds=10, delivery_fps=24,
        delivery_resolution="480p", aspect_ratio="16:9",
    ))
    shot = models.CinematicShot(
        shot_id="3" * 32, ordinal=1, title="Synthetic red clip",
        prompt="FFmpeg test color", duration_seconds=2,
    )
    scene = models.CinematicScene(
        scene_id="2" * 32, ordinal=1, title="Synthetic scene",
        target_duration_seconds=2, shots=[shot],
    )
    project = service.update_project(
        project.id, models.ProjectUpdateRequest(expected_revision=1, scenes=[scene]),
    )
    source_id = "4" * 32
    source = storage.video_asset_path(source_id, "mp4")
    _run(ffmpeg, "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "color=c=red:s=160x90:r=24:d=2",
         "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", str(source))
    _run(ffmpeg, "-nostdin", "-v", "error", "-xerror",
         "-i", str(source), "-an", "-f", "null", "-")
    job = storage.put_video_record("video_job", {
        "status": "succeeded", "project_id": project.id,
        "scene_id": scene.scene_id, "shot_id": shot.shot_id,
        "asset_id": source_id, "project_revision": project.revision,
    })
    linked = shot.model_copy(update={
        "latest_job_id": job["id"], "latest_rendered_project_revision": 2,
    })
    project = service.update_project(
        project.id, models.ProjectUpdateRequest(
            expected_revision=2,
            scenes=[scene.model_copy(update={"shots": [linked]})],
        ),
    )
    assert service.project_render_status(project.id)["ready_for_assembly"]
    master = service.assemble_project_master(
        project.id, requests.AssembleMasterRequest(expected_revision=project.revision),
    )
    assert master["status"] == "ready"
    assert master["actual_video_probe_verified"] is True
    assert master["probe"]["probe_metadata_verified"] is True
    output = storage.video_asset_path(master["asset_id"], "mp4")
    payload = output.read_bytes()
    assert len(payload) > 2048
    assert hashlib.sha256(payload).hexdigest() == master["sha256"]
    probe = json.loads(_run(
        ffprobe, "-v", "error", "-count_frames", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,nb_read_frames",
        "-of", "json", str(output),
    ).stdout)
    assert probe["streams"][0]["codec_name"] == "h264"
    assert int(probe["streams"][0]["nb_read_frames"]) == 48
    _run(ffmpeg, "-nostdin", "-v", "error", "-xerror",
         "-i", str(output), "-an", "-f", "null", "-")

    for name in ("app.studio.server", "app.video.router"):
        sys.modules.pop(name, None)
    server = importlib.import_module("app.studio.server")
    url = master["asset_url"]

    # Control: the same external address directly is already rejected.
    with TestClient(server.app, client=("198.51.100.24", 42001)) as remote:
        direct = remote.get(url)
        assert direct.status_code == 403
        assert direct.content != payload

    # Current explicit policy allows genuinely local requests without a token.
    with TestClient(server.app, client=("127.0.0.1", 42000)) as local:
        local_result = local.get(url)
        assert local_result.status_code == 200
        assert local_result.headers["cache-control"] == "no-store"
        assert local_result.content == payload

        # Model a reverse proxy on loopback forwarding an external client.
        # These headers are *not* proof of a trusted proxy; a safe fix may
        # require explicit proxy trust configuration or mandatory proxy auth.
        forwarded = {
            "Forwarded": "for=198.51.100.24;proto=https;host=cinema.example.invalid",
            "X-Forwarded-For": "198.51.100.24",
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "cinema.example.invalid",
        }
        proxied = local.get(url, headers=forwarded)
        assert proxied.status_code in (401, 403), (
            "A remote request forwarded through a loopback reverse proxy "
            "was treated as an unauthenticated local owner and served a private MP4"
        )
        assert proxied.content != payload

