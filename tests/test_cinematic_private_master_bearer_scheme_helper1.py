"""Helper 1 independent bearer-scheme QA for private, fully decoded cinematic masters.

The correct token alone is not a valid Authorization: Bearer credential.
This exercises actual H.264 encoding, FFprobe frame verification, full decode,
SHA-256 and private HTTP delivery; no owner footage or paid services.
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

from fastapi.testclient import TestClient
import pytest

TOKEN = "synthetic-owner-bearer-qa"


def _tools():
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        if os.getenv("CINEMATIC_REQUIRE_REAL_MEDIA") == "1":
            pytest.fail("Strict bearer QA requires genuine FFmpeg and FFprobe")
        pytest.skip("FFmpeg and FFprobe unavailable in ordinary CI")
    return ffmpeg, ffprobe


def _run(*args):
    return subprocess.run(args, check=True, capture_output=True, timeout=120)


def test_private_decoded_master_rejects_raw_token_without_bearer_scheme(
    monkeypatch, tmp_path: Path,
):
    ffmpeg, ffprobe = _tools()
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("CHARACTER3D_STUDIO_TOKEN", TOKEN)
    monkeypatch.setenv("CHARACTER3D_STUDIO_ORIGINS", "")

    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    storage = importlib.import_module("app.video.storage")
    project = service.create_project(models.ProjectCreateRequest(
        title="Bearer-only synthetic media", master_prompt="No owner footage",
        target_duration_seconds=10, delivery_fps=24,
        delivery_resolution="480p", aspect_ratio="16:9",
    ))
    shot = models.CinematicShot(
        shot_id="3" * 32, ordinal=1, title="Synthetic red",
        prompt="Synthetic FFmpeg test pattern", duration_seconds=2,
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

    for module in ("app.studio.server", "app.video.router"):
        sys.modules.pop(module, None)
    server = importlib.import_module("app.studio.server")
    correct = {"Authorization": f"Bearer {TOKEN}"}

    with TestClient(server.app) as client:
        assembled = client.post(
            f"/api/video/projects/{project.id}/assemble",
            json={"expected_revision": project.revision}, headers=correct,
        )
        assert assembled.status_code == 200, assembled.text
        master = assembled.json()
        assert master["status"] == "ready"
        assert master["actual_video_probe_verified"] is True
        assert master["probe"]["probe_metadata_verified"] is True
        path = storage.video_asset_path(master["asset_id"], "mp4")
        payload = path.read_bytes()
        assert len(payload) > 2048
        assert hashlib.sha256(payload).hexdigest() == master["sha256"]
        probe = json.loads(_run(
            ffprobe, "-v", "error", "-count_frames", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,nb_read_frames",
            "-of", "json", str(path),
        ).stdout)
        assert probe["streams"][0]["codec_name"] == "h264"
        assert int(probe["streams"][0]["nb_read_frames"]) == 48
        _run(ffmpeg, "-nostdin", "-v", "error", "-xerror",
             "-i", str(path), "-an", "-f", "null", "-")

        url = master["asset_url"]
        accepted = client.get(url, headers=correct)
        assert accepted.status_code == 200
        assert accepted.headers["cache-control"] == "no-store"
        assert accepted.content == payload

        for invalid in (
            {},
            {"Authorization": "Bearer wrong-token"},
            {"Authorization": f"Basic {TOKEN}"},
        ):
            denied = client.get(url, headers=invalid)
            assert denied.status_code == 401
            assert denied.content != payload
        query_only = client.get(url + f"?token={TOKEN}")
        assert query_only.status_code == 401

        # Regression contract: a bare secret is NOT an Authorization: Bearer
        # header, even if its bytes match the configured owner credential.
        bare = client.get(url, headers={"Authorization": TOKEN})
        assert bare.status_code == 401, (
            "Private MP4 accepted an unprefixed raw token as bearer auth; "
            "the server must require an explicit Bearer scheme."
        )
        assert bare.content != payload
