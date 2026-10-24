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


class _HoldingAssemblyPool:
    """Hold queued jobs without executing a second FFmpeg encode during HTTP QA."""

    def submit(self, fn, *args, **kwargs):
        return object()


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
    queue = importlib.import_module("app.video.cinematic_assembly_jobs")
    monkeypatch.setattr(queue, "assembly_pool", _HoldingAssemblyPool())
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

        # Master records expose private media identity and source provenance.
        # Both the synchronous assembly response and master-library JSON
        # require the same no-store protection as the underlying private MP4.
        masters = client.get(f"/api/video/projects/{project.id}/masters", headers=auth)
        assert masters.status_code == 200
        assert any(item.get("asset_id") == master["asset_id"] for item in masters.json())
        for denied_headers in ({}, {"Authorization": "Bearer wrong"}):
            denied_masters = client.get(
                f"/api/video/projects/{project.id}/masters", headers=denied_headers,
            )
            assert denied_masters.status_code == 401

        # The asynchronous mobile queue exposes project identity, revision,
        # FFmpeg settings and job state.  Even though it deliberately excludes
        # screenplay text, these owner-only operational records must not be
        # stored by browser or intermediary caches. Hold the worker to make
        # queued -> cancelled deterministic; the synchronous master above
        # already proved genuine H.264 encoding, probing and full decoding.
        queue_url = f"/api/video/projects/{project.id}/assembly-jobs"
        queued = client.post(
            queue_url, headers=auth,
            json={"expected_revision": project.revision},
        )
        assert queued.status_code == 202, queued.text
        queue_job = queued.json()
        assert queue_job["project_id"] == project.id
        assert queue_job["project_revision"] == project.revision
        assert queue_job["status"] == "queued"
        assert SENTINEL not in queued.text
        queue_detail_url = f"{queue_url}/{queue_job['id']}"
        queue_listing = client.get(queue_url, headers=auth)
        queue_detail = client.get(queue_detail_url, headers=auth)
        assert queue_listing.status_code == queue_detail.status_code == 200
        assert any(item["id"] == queue_job["id"] for item in queue_listing.json()["jobs"])
        assert queue_detail.json()["id"] == queue_job["id"]
        for private_url in (queue_url, queue_detail_url):
            assert client.get(private_url).status_code == 401
            assert client.get(private_url, headers={"Authorization": "Bearer wrong"}).status_code == 401
        denied_cancel = client.post(queue_detail_url + "/cancel")
        assert denied_cancel.status_code == 401
        assert queue.get_master_assembly_job(project.id, queue_job["id"])["status"] == "queued"
        queue_cancelled = client.post(queue_detail_url + "/cancel", headers=auth)
        assert queue_cancelled.status_code == 200
        assert queue_cancelled.json()["status"] == "cancelled"
        assert queue.get_master_assembly_job(project.id, queue_job["id"])["status"] == "cancelled"

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

        # The compiler returns the full project including the original
        # screenplay and newly generated shot text. A GET/POST/PUT-only
        # no-store fix would still expose this owner-authored JSON to caches.
        compiled = client.post(
            f"/api/video/projects/{created.json()['id']}/compile",
            headers=auth,
            json={
                "expected_revision": created.json()["revision"],
                "preferred_shot_seconds": 2,
                "engine_max_duration_seconds": 2,
            },
        )
        assert compiled.status_code == 200, compiled.status_code
        assert compiled.json()["project"]["master_prompt"] == SENTINEL
        assert compiled.json()["project"]["scenes"]
        assert compiled.json()["project"]["revision"] == created.json()["revision"] + 1
        # Authentication rejection must happen before any compile mutation.
        compiled_id = created.json()["id"]
        compiled_revision = compiled.json()["project"]["revision"]
        for denied_headers in ({}, {"Authorization": "Bearer wrong"}):
            denied = client.post(
                f"/api/video/projects/{compiled_id}/compile",
                headers=denied_headers,
                json={"expected_revision": compiled_revision},
            )
            assert denied.status_code == 401
        assert client.get(f"/api/video/projects/{compiled_id}", headers=auth).json()[
            "revision"
        ] == compiled_revision

        missing_no_store = []
        for route, response in (
            ("list", listing), ("detail", detail),
            ("create", created), ("update", updated), ("compile", compiled),
            ("assemble-master", assembled), ("master-library", masters),
            ("async-queue-create", queued), ("async-queue-list", queue_listing),
            ("async-queue-detail", queue_detail), ("async-queue-cancel", queue_cancelled),
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
