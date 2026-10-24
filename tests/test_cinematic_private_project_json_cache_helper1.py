"""Helper 1: private cinematic screenplay JSON must be non-cacheable.

Test-first, real-media integration proof using only synthetic H.264.  This
checks *project metadata* responses, not the already no-store MP4 asset route.
No owner footage, external inference, paid services or real credentials.
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

TOKEN = "synthetic-json-cache-owner-token"
SENTINEL = "SYNTHETIC_PRIVATE_SCREENPLAY_CACHE_SENTINEL_8f4d"


def _media_tools():
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        if os.getenv("CINEMATIC_REQUIRE_REAL_MEDIA") == "1":
            pytest.fail("Strict project-JSON privacy QA requires real FFmpeg and FFprobe")
        pytest.skip("Real FFmpeg and FFprobe unavailable in ordinary CI")
    return ffmpeg, ffprobe


def _run(*command):
    return subprocess.run(command, check=True, capture_output=True, timeout=120)


def test_private_project_json_never_advertises_cacheable_screenplay(
    monkeypatch, tmp_path: Path,
):
    ffmpeg, ffprobe = _media_tools()
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("CHARACTER3D_STUDIO_TOKEN", TOKEN)
    monkeypatch.setenv("CHARACTER3D_STUDIO_ORIGINS", "")

    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    storage = importlib.import_module("app.video.storage")

    project = service.create_project(models.ProjectCreateRequest(
        title="Synthetic private screenplay", master_prompt=SENTINEL,
        target_duration_seconds=10, delivery_fps=24,
        delivery_resolution="480p", aspect_ratio="16:9",
    ))
    shot = models.CinematicShot(
        shot_id="3" * 32, ordinal=1, title="Synthetic red",
        prompt="Synthetic FFmpeg red frame", duration_seconds=2,
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
    _run(
        ffmpeg, "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=red:s=160x90:r=24:d=2",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(source),
    )
    source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
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
    auth = {"Authorization": f"Bearer {TOKEN}"}

    with TestClient(server.app) as client:
        assembled = client.post(
            f"/api/video/projects/{project.id}/assemble",
            json={"expected_revision": project.revision}, headers=auth,
        )
        assert assembled.status_code == 200, assembled.status_code
        master = assembled.json()
        assert master["status"] == "ready"
        assert master["actual_video_probe_verified"] is True
        output = storage.video_asset_path(master["asset_id"], "mp4")
        data = output.read_bytes()
        assert len(data) > 2048
        assert hashlib.sha256(data).hexdigest() == master["sha256"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == source_digest
        probe = json.loads(_run(
            ffprobe, "-v", "error", "-count_frames", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,nb_read_frames",
            "-of", "json", str(output),
        ).stdout)
        assert probe["streams"][0]["codec_name"] == "h264"
        assert int(probe["streams"][0]["nb_read_frames"]) == 48
        _run(ffmpeg, "-nostdin", "-v", "error", "-xerror",
             "-i", str(output), "-an", "-f", "null", "-")

        media = client.get(master["asset_url"], headers=auth)
        assert media.status_code == 200
        assert media.headers.get("cache-control") == "no-store"
        assert media.content == data

        # No Authorization header or query token may retrieve screenplay JSON.
        for route in ("/api/video/projects", f"/api/video/projects/{project.id}"):
            assert client.get(route).status_code == 401
            assert client.get(route, headers={"Authorization": "Bearer wrong"}).status_code == 401
            assert client.get(route + "?token=" + TOKEN).status_code == 401

        # The private JSON routes return the raw creative screenplay, unlike
        # media files that already set no-store. Browser/proxy caches must
        # never be invited to retain these owner-only JSON representations.
        listing = client.get("/api/video/projects", headers=auth)
        detail = client.get(f"/api/video/projects/{project.id}", headers=auth)
        assert listing.status_code == detail.status_code == 200
        assert any(item.get("master_prompt") == SENTINEL for item in listing.json())
        assert detail.json()["master_prompt"] == SENTINEL
        # Creation and updates also return the complete private screenplay.
        # Checking only GET routes would permit a partial middleware fix to
        # leave these authenticated mutation responses cacheable.
        created = client.post("/api/video/projects", headers=auth, json={
            "title": "Another synthetic private film",
            "master_prompt": SENTINEL,
            "target_duration_seconds": 10,
            "delivery_fps": 24,
            "delivery_resolution": "480p",
            "aspect_ratio": "16:9",
        })
        updated = client.put(
            f"/api/video/projects/{project.id}", headers=auth,
            json={"expected_revision": project.revision, "title": "Private screenplay revised"},
        )
        assert created.status_code == updated.status_code == 200
        assert created.json()["master_prompt"] == SENTINEL
        assert updated.json()["master_prompt"] == SENTINEL

        missing_no_store = []
        for route, response in (
            ("list", listing), ("detail", detail),
            ("create", created), ("update", updated),
        ):
            directives = {
                part.strip().lower()
                for part in response.headers.get("cache-control", "").split(",")
            }
            if "no-store" not in directives:
                missing_no_store.append(route)
        assert not missing_no_store, (
            "Private screenplay JSON lacks Cache-Control: no-store on: "
            + ", ".join(missing_no_store)
        )
