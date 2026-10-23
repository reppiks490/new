"""Helper 1: real-media, authenticated cancellation/recovery acceptance.

Synthetic H.264 only. The queue's executor is held for deterministic API races;
the replacement job is then executed with genuine FFmpeg and fully decoded.
No owner footage, GPU, paid services, or private credentials are involved.
"""
from __future__ import annotations

import hashlib
import importlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient


class HeldExecutor:
    def __init__(self):
        self.submissions = []

    def submit(self, fn, *args, **kwargs):
        self.submissions.append((fn, args, kwargs))
        return object()


def _media_tools():
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        if os.environ.get("CINEMATIC_REQUIRE_REAL_MEDIA") == "1":
            pytest.fail("Strict cancellation acceptance requires real ffmpeg and ffprobe")
        pytest.skip("FFmpeg/ffprobe unavailable in ordinary Python acceptance")
    return ffmpeg, ffprobe


def _run(*args):
    return subprocess.run(args, check=True, capture_output=True, timeout=120)


def test_cancelled_private_master_never_encodes_after_recovery_but_new_job_does(
    monkeypatch, tmp_path: Path
):
    ffmpeg, ffprobe = _media_tools()
    secret = "synthetic-private-cancel-token"
    marker = "PRIVATE_CANCEL_SCREENPLAY_CANARY"
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("CHARACTER3D_STUDIO_TOKEN", secret)
    monkeypatch.setenv("CHARACTER3D_STUDIO_ORIGINS", "")

    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    storage = importlib.import_module("app.video.storage")
    queue = importlib.import_module("app.video.cinematic_assembly_jobs")
    pool = HeldExecutor()
    monkeypatch.setattr(queue, "assembly_pool", pool)

    project = service.create_project(models.ProjectCreateRequest(
        title="Synthetic cancellation proof",
        master_prompt=marker,
        target_duration_seconds=10,
        delivery_fps=24,
        delivery_resolution="480p",
        aspect_ratio="16:9",
    ))
    other = service.create_project(models.ProjectCreateRequest(
        title="Unrelated synthetic project",
        master_prompt="OTHER_PRIVATE_PROJECT",
        target_duration_seconds=10,
        delivery_fps=24,
        delivery_resolution="480p",
        aspect_ratio="16:9",
    ))
    shot = models.CinematicShot(
        shot_id="b" * 32, ordinal=1, title="Test shot",
        prompt="Synthetic FFmpeg color clip", duration_seconds=2,
    )
    scene = models.CinematicScene(
        scene_id="a" * 32, ordinal=1, title="Test scene",
        target_duration_seconds=2, shots=[shot],
    )
    project = service.update_project(
        project.id, models.ProjectUpdateRequest(expected_revision=1, scenes=[scene])
    )
    source_id = "c" * 32
    source = storage.video_asset_path(source_id, "mp4")
    _run(
        ffmpeg, "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=red:s=160x90:r=24:d=2",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(source),
    )
    _run(ffmpeg, "-nostdin", "-v", "error", "-xerror",
         "-i", str(source), "-an", "-f", "null", "-")
    rendered = storage.put_video_record("video_job", {
        "status": "succeeded", "project_id": project.id,
        "scene_id": scene.scene_id, "shot_id": shot.shot_id,
        "asset_id": source_id, "project_revision": project.revision,
    })
    linked = shot.model_copy(update={
        "latest_job_id": rendered["id"], "latest_rendered_project_revision": 2,
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
    auth = {"Authorization": f"Bearer {secret}"}
    base = f"/api/video/projects/{project.id}/assembly-jobs"
    other_base = f"/api/video/projects/{other.id}/assembly-jobs"

    with TestClient(server.app) as client:
        submitted = client.post(
            base, json={"expected_revision": project.revision}, headers=auth,
        )
        assert submitted.status_code == 202, submitted.text
        job = submitted.json()
        assert job["status"] == "queued"
        own_cancel = f"{base}/{job['id']}/cancel"
        other_cancel = f"{other_base}/{job['id']}/cancel"

        for headers, params, expected in (
            ({}, {}, 401),
            ({"Authorization": "Bearer wrong"}, {}, 401),
            ({}, {"token": secret}, 401),
            ({**auth, "Origin": "https://foreign.invalid"}, {}, 403),
        ):
            denied = client.post(own_cancel, headers=headers, params=params)
            assert denied.status_code == expected, denied.text
            assert marker not in denied.text
            assert secret not in denied.text
            assert queue.get_master_assembly_job(project.id, job["id"])["status"] == "queued"

        cross = client.post(other_cancel, headers=auth)
        assert cross.status_code == 404, cross.text
        assert marker not in cross.text
        assert queue.get_master_assembly_job(project.id, job["id"])["status"] == "queued"

        cancelled = client.post(own_cancel, headers=auth)
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "cancelled"
        assert marker not in cancelled.text
        assert secret not in cancelled.text
        again = client.post(own_cancel, headers=auth)
        assert again.status_code == 200
        assert again.json()["id"] == job["id"]
        assert again.json()["status"] == "cancelled"

        # Simulated restart and delayed executor callbacks cannot resurrect it.
        assert queue.recover_assembly_queue()["interrupted"] == 0
        for fn, args, kwargs in list(pool.submissions):
            fn(*args, **kwargs)
        assert queue.get_master_assembly_job(project.id, job["id"])["status"] == "cancelled"
        assert storage.list_video_records("video_master") == []

        # A new explicit owner submission is not blocked by the old receipt.
        retry = client.post(
            base, json={"expected_revision": project.revision}, headers=auth,
        )
        assert retry.status_code == 202, retry.text
        assert retry.json()["id"] != job["id"]
        queue._drain()
        completed = client.get(f"{base}/{retry.json()['id']}", headers=auth)
        assert completed.status_code == 200, completed.text
        result = completed.json()
        assert result["status"] == "succeeded", result
        assert result["probe_metadata_verified"] is True
        assert queue.get_master_assembly_job(project.id, job["id"])["status"] == "cancelled"
        assert len(storage.list_video_records("video_master")) == 1
        output = storage.video_asset_path(result["asset_id"], "mp4")
        assert hashlib.sha256(output.read_bytes()).hexdigest() == result["sha256"]
        _run(ffprobe, "-v", "error", "-count_frames", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name,nb_read_frames",
             "-of", "default=noprint_wrappers=1", str(output))
        _run(ffmpeg, "-nostdin", "-v", "error", "-xerror",
             "-i", str(output), "-an", "-f", "null", "-")
        assert client.get(result["asset_url"]).status_code == 401
        authorized = client.get(result["asset_url"], headers=auth)
        assert authorized.status_code == 200
        assert authorized.headers["cache-control"] == "no-store"
        assert hashlib.sha256(authorized.content).hexdigest() == result["sha256"]
        assert marker not in completed.text
        assert secret not in completed.text
