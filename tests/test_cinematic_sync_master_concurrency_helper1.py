"""Helper 1: test-first, real-media proof for duplicate synchronous master races.

Only generated H.264 color footage. Two callers share the same project revision.
The first FFmpeg invocation is held briefly so a competing caller can observe
the same cache miss. A future correct implementation may serialize before that
point: the hold is bounded and then permits the first encode to finish.
No owner footage, GPU, credentials, paid services or external APIs.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading

import pytest


def _tools():
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        if os.getenv("CINEMATIC_REQUIRE_REAL_MEDIA") == "1":
            pytest.fail("Strict concurrent-master QA requires FFmpeg and FFprobe")
        pytest.skip("FFmpeg/FFprobe not available in ordinary CI")
    return ffmpeg, ffprobe


def _run(*command):
    return subprocess.run(command, capture_output=True, text=True, check=True, timeout=120)


def test_two_same_revision_assemble_calls_publish_only_one_master(monkeypatch, tmp_path: Path):
    ffmpeg, ffprobe = _tools()
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    service = importlib.import_module("app.video.cinematic_service")
    models = importlib.import_module("app.video.cinematic_models")
    storage = importlib.import_module("app.video.storage")
    requests = importlib.import_module("app.video.cinematic_requests")

    project = service.create_project(models.ProjectCreateRequest(
        title="Synthetic concurrent master", master_prompt="No private footage",
        target_duration_seconds=10, delivery_fps=24,
        delivery_resolution="480p", aspect_ratio="16:9",
    ))
    shot = models.CinematicShot(
        shot_id="b" * 32, ordinal=1, title="One synthetic shot",
        prompt="solid red", duration_seconds=2,
    )
    scene = models.CinematicScene(
        scene_id="a" * 32, ordinal=1, title="Scene", target_duration_seconds=2,
        shots=[shot],
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
    source_info = json.loads(_run(
        ffprobe, "-v", "error", "-count_frames", "-select_streams", "v:0",
        "-show_entries", "stream=nb_read_frames", "-of", "json", str(source),
    ).stdout)
    assert int(source_info["streams"][0]["nb_read_frames"]) == 48

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

    # Hold the first encode for at most 4 seconds. The second caller can now
    # reach the same cache miss in the current implementation. A correct lock
    # before the cache check may make only one invocation reach this seam.
    original = service._run_master_ffmpeg
    start = threading.Barrier(2)
    lock = threading.Lock()
    encode_lock = threading.Lock()
    second_entered = threading.Event()
    calls = []

    def intercepted(command, **kwargs):
        with lock:
            calls.append(command)
            ordinal = len(calls)
            if ordinal >= 2:
                second_entered.set()
        if ordinal == 1:
            second_entered.wait(timeout=4)
        # Serialize the actual encodes to avoid runner-dependent libx264
        # resource contention. Both cache decisions already happened.
        with encode_lock:
            return original(command, **kwargs)

    monkeypatch.setattr(service, "_run_master_ffmpeg", intercepted)
    request = requests.AssembleMasterRequest(expected_revision=project.revision)

    def assemble():
        start.wait(timeout=15)
        return service.assemble_project_master(project.id, request)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(assemble) for _ in range(2)]
        results = [future.result(timeout=120) for future in futures]

    for result in results:
        assert result["status"] == "ready"
        path = storage.video_asset_path(result["asset_id"], "mp4")
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == result["sha256"]
        probe = json.loads(_run(
            ffprobe, "-v", "error", "-count_frames", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,nb_read_frames",
            "-of", "json", str(path),
        ).stdout)
        assert probe["streams"][0]["codec_name"] == "h264"
        assert int(probe["streams"][0]["nb_read_frames"]) == 48
        _run(ffmpeg, "-nostdin", "-v", "error", "-xerror",
             "-i", str(path), "-an", "-f", "null", "-")

    # Repeated submissions of the same immutable revision/source should be
    # one published master, not two expensive encodes and duplicate records.
    masters = [item for item in storage.list_video_records("video_master")
               if item.get("project_id") == project.id]
    assert len(masters) == 1, (
        f"Concurrent identical assembly published {len(masters)} ready master records"
    )
    assert len(calls) == 1, (
        f"Concurrent identical assembly executed FFmpeg {len(calls)} times"
    )
    assert results[0]["id"] == results[1]["id"] == masters[0]["id"]
