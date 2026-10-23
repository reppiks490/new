"""Helper 1: queued master must not silently adopt changed shot bytes.

Synthetic RED H.264 is the authenticated queue intent. The linked asset is
atomically replaced by valid BLUE H.264 while the job is still queued.
A successful result must retain the original input snapshot; otherwise the
queue must fail closed without publishing a ready master. No owner media.
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


class HeldExecutor:
    def submit(self, fn, *args, **kwargs):
        return object()


def _tools():
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        if os.getenv("CINEMATIC_REQUIRE_REAL_MEDIA") == "1":
            pytest.fail("Strict queued-input provenance QA requires FFmpeg and FFprobe")
        pytest.skip("FFmpeg/FFprobe unavailable in ordinary CI")
    return ffmpeg, ffprobe


def _run(*args):
    return subprocess.run(args, check=True, capture_output=True, timeout=120)


def _make_clip(ffmpeg, path: Path, color: str):
    _run(ffmpeg, "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", f"color=c={color}:s=160x90:r=24:d=2",
         "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", str(path))


def _prove_clip(ffmpeg, ffprobe, path: Path):
    probe = json.loads(_run(
        ffprobe, "-v", "error", "-count_frames", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,nb_read_frames",
        "-of", "json", str(path),
    ).stdout)
    stream, = probe["streams"]
    assert stream["codec_name"] == "h264"
    assert int(stream["nb_read_frames"]) == 48
    _run(ffmpeg, "-nostdin", "-v", "error", "-xerror",
         "-i", str(path), "-an", "-f", "null", "-")
    pixel = _run(
        ffmpeg, "-nostdin", "-v", "error", "-i", str(path),
        "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ).stdout[:3]
    assert len(pixel) == 3
    return tuple(pixel)


def test_queued_master_rejects_source_replacement_before_worker_claim(
    monkeypatch, tmp_path: Path,
):
    ffmpeg, ffprobe = _tools()
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("CHARACTER3D_STUDIO_TOKEN", "synthetic-private-owner")
    monkeypatch.setenv("CHARACTER3D_STUDIO_ORIGINS", "")

    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    storage = importlib.import_module("app.video.storage")
    queue = importlib.import_module("app.video.cinematic_assembly_jobs")
    monkeypatch.setattr(queue, "assembly_pool", HeldExecutor())

    project = service.create_project(models.ProjectCreateRequest(
        title="Queued source integrity", master_prompt="Synthetic only",
        target_duration_seconds=10, delivery_fps=24,
        delivery_resolution="480p", aspect_ratio="16:9",
    ))
    shot = models.CinematicShot(
        shot_id="3" * 32, ordinal=1, title="Color", prompt="No inference",
        duration_seconds=2,
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
    _make_clip(ffmpeg, source, "red")
    red_pixel = _prove_clip(ffmpeg, ffprobe, source)
    assert red_pixel[0] > 200 and red_pixel[2] < 50
    red_sha = hashlib.sha256(source.read_bytes()).hexdigest()

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

    for name in ("app.studio.server", "app.video.router"):
        sys.modules.pop(name, None)
    server = importlib.import_module("app.studio.server")
    route = f"/api/video/projects/{project.id}/assembly-jobs"
    auth = {"Authorization": "Bearer synthetic-private-owner"}
    with TestClient(server.app) as client:
        assert client.post(route, json={"expected_revision": project.revision}).status_code == 401
        queued_response = client.post(
            route, json={"expected_revision": project.revision}, headers=auth,
        )
        assert queued_response.status_code == 202, queued_response.text
        receipt = queued_response.json()
        assert receipt["status"] == "queued"
        assert receipt["project_revision"] == project.revision

        # Swap a fully valid video into the same opaque asset ID after
        # admission, before the worker claims the queued request.
        blue_tmp = storage.video_asset_path("5" * 32, "mp4")
        _make_clip(ffmpeg, blue_tmp, "blue")
        blue_pixel = _prove_clip(ffmpeg, ffprobe, blue_tmp)
        assert blue_pixel[2] > 200 and blue_pixel[0] < 50
        os.replace(blue_tmp, source)
        blue_sha = hashlib.sha256(source.read_bytes()).hexdigest()
        assert red_sha != blue_sha
        assert service.get_project(project.id).revision == project.revision
        assert _prove_clip(ffmpeg, ffprobe, source)[2] > 200

        # Real SQLite claim, real FFmpeg assembly, and full output decode.
        queue._drain()
        response = client.get(f"{route}/{receipt['id']}", headers=auth)
        assert response.status_code == 200, response.text
        job = response.json()
        masters = [
            item for item in storage.list_video_records("video_master")
            if item.get("project_id") == project.id
        ]
        if job["status"] == "failed":
            assert not masters, "Failed queued input still published a ready master"
            return

        assert job["status"] == "succeeded", job
        assert len(masters) == 1
        master = masters[0]
        output = storage.video_asset_path(master["asset_id"], "mp4")
        assert hashlib.sha256(output.read_bytes()).hexdigest() == job["sha256"]
        master_pixel = _prove_clip(ffmpeg, ffprobe, output)
        assert client.get(job["asset_url"]).status_code == 401
        downloaded = client.get(job["asset_url"], headers=auth)
        assert downloaded.status_code == 200
        assert downloaded.headers["cache-control"] == "no-store"
        assert hashlib.sha256(downloaded.content).hexdigest() == job["sha256"]

        assert master["source_asset_hashes"] == [red_sha] and master_pixel[0] > 200, (
            "Queued RED source was replaced by BLUE before execution, yet the "
            "job silently published a BLUE ready master for the old queue intent: "
            f"queued_sha={red_sha[:12]}, actual_sha={blue_sha[:12]}, "
            f"decoded_rgb={master_pixel}"
        )
