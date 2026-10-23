"""End-to-end local-only HTTP queue -> real FFmpeg -> private MP4 acceptance.

Unlike mocked queue tests, this executes the actual assembly worker with
two synthetic media files, polls authenticated endpoints, and decodes the
result. No paid inference, GPU, owner imagery, or public upload.
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


class HeldExecutor:
    """Make HTTP enqueue deterministic: execution is explicitly advanced in test."""
    def __init__(self):
        self.tasks = []

    def submit(self, fn, *args, **kwargs):
        self.tasks.append((fn, args, kwargs))
        return object()


def _tools() -> tuple[str, str]:
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        if os.getenv("CINEMATIC_REQUIRE_REAL_MEDIA") == "1":
            pytest.fail("Real async acceptance requires ffmpeg AND ffprobe")
        pytest.skip("ffmpeg and ffprobe not available in ordinary Python matrix")
    return ffmpeg, ffprobe


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=True, capture_output=True, timeout=120)


def test_private_http_async_queue_yields_genuinely_decodable_mp4_and_reuses_cache(
    monkeypatch, tmp_path: Path
):
    ffmpeg, ffprobe = _tools()
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("CHARACTER3D_STUDIO_TOKEN", "synthetic-test-owner-secret")
    monkeypatch.setenv("CHARACTER3D_STUDIO_ORIGINS", "")

    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    storage = importlib.import_module("app.video.storage")
    queue = importlib.import_module("app.video.cinematic_assembly_jobs")
    pool = HeldExecutor()
    monkeypatch.setattr(queue, "assembly_pool", pool)

    project = service.create_project(models.ProjectCreateRequest(
        title="Synthetic queued assembly",
        master_prompt="PRIVATE_SCRIPT_CANARY must never enter assembly responses",
        target_duration_seconds=10,
        delivery_fps=24,
        delivery_resolution="480p",
        aspect_ratio="16:9",
    ))
    scene_id = "1" * 32
    shots = [
        models.CinematicShot(
            shot_id=f"{index + 40:032x}", ordinal=index + 1,
            title=f"Synthetic shot {index + 1}", prompt="No inference used",
            duration_seconds=5,
        ) for index in range(2)
    ]
    scene = models.CinematicScene(
        scene_id=scene_id, ordinal=1, title="Test reel",
        target_duration_seconds=10, shots=shots,
    )
    project = service.update_project(
        project.id, models.ProjectUpdateRequest(expected_revision=1, scenes=[scene]),
    )
    links = []
    for index, (color, fps) in enumerate((("red", 24), ("blue", 30))):
        asset_id = f"{index + 120:032x}"
        path = storage.video_asset_path(asset_id, "mp4")
        _run([
            ffmpeg, "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=160x90:r={fps}:d=5",
            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(path),
        ])
        record = storage.put_video_record("video_job", {
            "status": "succeeded", "stage": "Ready", "progress": 100,
            "project_id": project.id, "scene_id": scene_id,
            "shot_id": shots[index].shot_id,
            "project_revision": project.revision, "asset_id": asset_id,
            "asset_url": f"/api/video/assets/{asset_id}.mp4",
        })
        links.append(shots[index].model_copy(update={
            "latest_job_id": record["id"], "latest_rendered_project_revision": 2,
        }))
    project = service.update_project(
        project.id, models.ProjectUpdateRequest(
            expected_revision=2, scenes=[scene.model_copy(update={"shots": links})],
        ),
    )
    assert service.project_render_status(project.id)["ready_for_assembly"]

    # Import the real API after the bearer env is set. A held executor keeps
    # both the startup recovery and HTTP submission from racing the test.
    for name in ("app.studio.server", "app.video.router"):
        sys.modules.pop(name, None)
    server = importlib.import_module("app.studio.server")
    bearer = {"Authorization": "Bearer synthetic-test-owner-secret"}
    base = f"/api/video/projects/{project.id}/assembly-jobs"

    with TestClient(server.app) as client:
        denied = client.post(base, json={"expected_revision": project.revision})
        assert denied.status_code == 401
        assert queue.list_master_assembly_jobs(project.id)["total"] == 0

        accepted = client.post(
            base, json={"expected_revision": project.revision}, headers=bearer,
        )
        assert accepted.status_code == 202, accepted.text
        queued = accepted.json()
        assert queued["status"] == "queued"
        assert queued["project_revision"] == project.revision
        assert "PRIVATE_SCRIPT_CANARY" not in accepted.text
        assert "synthetic-test-owner-secret" not in accepted.text

        detail_path = f"{base}/{queued['id']}"
        before = client.get(detail_path, headers=bearer)
        assert before.status_code == 200
        assert before.json()["status"] == "queued"
        assert client.get(detail_path).status_code == 401

        # Real queue claim + actual FFmpeg and FFprobe, not a mock function.
        queue._drain()
        completed = client.get(detail_path, headers=bearer)
        assert completed.status_code == 200, completed.text
        job = completed.json()
        assert job["status"] == "succeeded", job
        assert job["stage"] == "Ready"
        assert job["progress"] == 100
        assert job["probe_metadata_verified"] is True
        assert "PRIVATE_SCRIPT_CANARY" not in completed.text

        private_url = job["asset_url"]
        assert private_url.startswith("/api/video/assets/")
        assert "token=" not in private_url
        assert client.get(private_url).status_code == 401
        assert client.get(private_url, params={"token": "synthetic-test-owner-secret"}).status_code == 401
        media = client.get(private_url, headers=bearer)
        assert media.status_code == 200
        assert media.headers["cache-control"] == "no-store"
        assert media.headers["content-type"].startswith("video/mp4")
        assert hashlib.sha256(media.content).hexdigest() == job["sha256"]
        assert media.content[:12].find(b"ftyp") >= 0

        master = storage.get_video_record("video_master", job["master_id"])
        output = storage.video_asset_path(job["asset_id"], "mp4")
        assert master["project_revision"] == project.revision
        assert master["actual_video_probe_verified"] is True
        assert output.read_bytes() == media.content
        metadata = json.loads(_run([
            ffprobe, "-v", "error", "-show_format", "-show_streams",
            "-of", "json", str(output),
        ]).stdout)
        stream, = [s for s in metadata["streams"] if s["codec_type"] == "video"]
        assert stream["codec_name"] == "h264"
        assert (stream["width"], stream["height"]) == (854, 480)
        assert float(metadata["format"]["duration"]) == pytest.approx(10, abs=0.25)
        _run([ffmpeg, "-nostdin", "-v", "error", "-xerror",
              "-i", str(output), "-an", "-f", "null", "-"])

        # A second user submit after completion may create a fresh queue
        # receipt, but it must reuse the same verified master bytes and ID.
        next_submit = client.post(
            base, json={"expected_revision": project.revision}, headers=bearer,
        )
        assert next_submit.status_code == 202, next_submit.text
        second = next_submit.json()
        assert second["id"] != queued["id"]
        queue._drain()
        after = client.get(f"{base}/{second['id']}", headers=bearer)
        assert after.status_code == 200 and after.json()["status"] == "succeeded"
        assert after.json()["master_id"] == job["master_id"]
        assert len(storage.list_video_records("video_master")) == 1
        assert service.get_project(project.id).revision == project.revision
