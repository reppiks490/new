"""Helper 1: a second API worker startup must not orphan a live FFmpeg job.

This test uses synthetic H.264 only. The first worker has already claimed the
SQLite job and entered assembly when another server startup runs recovery.
A healthy live worker must retain its claim or be explicitly fenced before
publishing, rather than silently producing a ready master for a failed receipt.
No private footage, credentials, paid services, or deployment are involved.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib
import os
from pathlib import Path
import shutil
import subprocess
import threading

import pytest


class HeldPool:
    def submit(self, fn, *args, **kwargs):
        # Prevent background dispatch: test explicitly drives the first worker.
        return object()


def _tools():
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        if os.getenv("CINEMATIC_REQUIRE_REAL_MEDIA") == "1":
            pytest.fail("Strict live-worker recovery QA requires FFmpeg and FFprobe")
        pytest.skip("FFmpeg/FFprobe not available in ordinary CI")
    return ffmpeg, ffprobe


def _run(*command):
    return subprocess.run(command, check=True, capture_output=True, timeout=120)


def test_second_worker_startup_does_not_fail_healthy_running_master(
    monkeypatch, tmp_path: Path,
):
    ffmpeg, ffprobe = _tools()
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    storage = importlib.import_module("app.video.storage")
    queue = importlib.import_module("app.video.cinematic_assembly_jobs")
    requests = importlib.import_module("app.video.cinematic_requests")
    monkeypatch.setattr(queue, "assembly_pool", HeldPool())

    project = service.create_project(models.ProjectCreateRequest(
        title="Synthetic live worker", master_prompt="No owner content",
        target_duration_seconds=10, delivery_fps=24,
        delivery_resolution="480p", aspect_ratio="16:9",
    ))
    shot = models.CinematicShot(
        shot_id="b" * 32, ordinal=1, title="Color source",
        prompt="Synthetic red clip", duration_seconds=2,
    )
    scene = models.CinematicScene(
        scene_id="a" * 32, ordinal=1, title="Scene",
        target_duration_seconds=2, shots=[shot],
    )
    project = service.update_project(
        project.id, models.ProjectUpdateRequest(expected_revision=1, scenes=[scene]),
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

    job = queue.enqueue_master_assembly(
        project.id, requests.AssembleMasterRequest(expected_revision=project.revision),
    )
    assert job["status"] == "queued"

    entered_encode = threading.Event()
    release_encode = threading.Event()
    original_encode = service._run_master_ffmpeg

    def pause_before_real_encode(command, **kwargs):
        entered_encode.set()
        if not release_encode.wait(timeout=12):
            raise TimeoutError("Timed out waiting for concurrent startup recovery")
        return original_encode(command, **kwargs)

    monkeypatch.setattr(service, "_run_master_ffmpeg", pause_before_real_encode)
    with ThreadPoolExecutor(max_workers=1) as worker_pool:
        worker = worker_pool.submit(queue._drain)
        try:
            assert entered_encode.wait(timeout=12), "Worker never entered FFmpeg"
            assert queue.get_master_assembly_job(project.id, job["id"])["status"] == "running"
            # Models another API process entering its startup hook while the
            # existing process is still alive. SQLite is shared by both.
            recovered = queue.recover_assembly_queue()
        finally:
            release_encode.set()
        worker.result(timeout=120)

    # Genuine media proof is completed *before* evaluating the job contract.
    masters = [
        record for record in storage.list_video_records("video_master")
        if record.get("project_id") == project.id
    ]
    for master in masters:
        output = storage.video_asset_path(master["asset_id"], "mp4")
        assert output.is_file()
        assert hashlib.sha256(output.read_bytes()).hexdigest() == master["sha256"]
        _run(
            ffprobe, "-v", "error", "-count_frames", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,nb_read_frames",
            "-of", "default=noprint_wrappers=1", str(output),
        )
        _run(ffmpeg, "-nostdin", "-v", "error", "-xerror",
             "-i", str(output), "-an", "-f", "null", "-")

    final = queue.get_master_assembly_job(project.id, job["id"])
    assert recovered["interrupted"] == 0, (
        "A second API worker startup misclassified an actively encoding "
        "healthy job as interrupted"
    )
    assert final["status"] == "succeeded", (
        f"Live worker completed FFmpeg but durable job status is {final['status']}"
    )
    assert len(masters) == 1
    assert final["master_id"] == masters[0]["id"]
