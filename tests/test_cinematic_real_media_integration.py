"""Proof that the cinematic master assembly creates decodable local media.

Runs two genuine, synthetic FFmpeg clips through the implementation branch's
master assembly. No inference engine, network, owner images or paid services.
A passing test proves only this short CPU-only media fixture, not 600-second
GPU generation, creative continuity, iPhone playback or release readiness.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

import pytest


SCENE_ID = "e" * 32


def _require_video_tools() -> tuple[str, str]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        message = "Real-media acceptance requires both local ffmpeg and ffprobe"
        if os.environ.get("CI") == "true":
            pytest.fail(message)
        pytest.skip(message)
    return ffmpeg, ffprobe


def _run(command: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    )


def _synthetic_clip(ffmpeg: str, path: Path, *, color: str, fps: int) -> None:
    _run([
        ffmpeg, "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi",
        "-i", f"color=c={color}:s=160x90:r={fps}:d=5",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(path),
    ])
    assert path.is_file() and path.stat().st_size > 128


def test_real_ffmpeg_master_has_decodable_ordered_video_and_verified_bytes(
    monkeypatch, tmp_path: Path
):
    ffmpeg, ffprobe = _require_video_tools()
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    requests = importlib.import_module("app.video.cinematic_requests")
    storage = importlib.import_module("app.video.storage")

    created = service.create_project(models.ProjectCreateRequest(
        title="Synthetic offline media acceptance",
        master_prompt="SCENE 1: Test slate. Red shot followed by blue shot.",
        target_duration_seconds=10,
        delivery_fps=24,
        delivery_resolution="480p",
        aspect_ratio="16:9",
        reference_image_ids=[],
    ))
    shots = [
        models.CinematicShot(
            shot_id=f"{index + 10:032x}",
            ordinal=index + 1,
            title=f"Local shot {index + 1}",
            prompt="Synthetic footage, no generative model.",
            duration_seconds=5,
        )
        for index in range(2)
    ]
    scene = models.CinematicScene(
        scene_id=SCENE_ID, ordinal=1, title="Test slate",
        source_text="Red to blue", target_duration_seconds=10, shots=shots,
    )
    project = service.update_project(
        created.id,
        models.ProjectUpdateRequest(expected_revision=1, scenes=[scene]),
    )
    assert project.revision == 2

    linked = []
    for index, (color, fps) in enumerate((("red", 24), ("blue", 30))):
        asset_id = f"{index + 100:032x}"
        source = storage.video_asset_path(asset_id, "mp4")
        _synthetic_clip(ffmpeg, source, color=color, fps=fps)
        job = storage.put_video_record("video_job", {
            "status": "succeeded",
            "stage": "Ready",
            "progress": 100,
            "image_id": "0" * 32,
            "prompt_chars": 8,
            "fps": fps,
            "resolution": "480p",
            "duration_seconds": 5,
            "project_id": project.id,
            "scene_id": SCENE_ID,
            "shot_id": shots[index].shot_id,
            "project_revision": 2,
            "asset_id": asset_id,
            "asset_url": f"/api/video/assets/{asset_id}.mp4",
        })
        linked.append(shots[index].model_copy(update={
            "latest_job_id": job["id"], "latest_rendered_project_revision": 2,
        }))

    project = service.update_project(
        project.id,
        models.ProjectUpdateRequest(
            expected_revision=2,
            scenes=[scene.model_copy(update={"shots": linked})],
        ),
    )
    assert project.revision == 3
    assert service.project_render_status(project.id)["ready_for_assembly"]

    master = service.assemble_project_master(
        project.id,
        requests.AssembleMasterRequest(
            expected_revision=project.revision, ffmpeg_path=ffmpeg,
        ),
    )
    output = storage.video_asset_path(master["asset_id"], "mp4")
    assert master["status"] == "ready"
    assert output.is_file()
    assert master["source_shot_ids"] == [shot.shot_id for shot in shots]
    assert master["source_shot_count"] == 2
    assert master["project_revision"] == 3
    assert master["size_bytes"] == output.stat().st_size
    assert master["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert service.get_project(project.id).revision == 3

    probe = json.loads(_run([
        ffprobe, "-v", "error", "-show_streams", "-show_format",
        "-of", "json", str(output),
    ]).stdout)
    videos = [stream for stream in probe["streams"]
              if stream["codec_type"] == "video"]
    assert len(videos) == 1, probe
    stream = videos[0]
    assert stream["codec_name"] == "h264", probe
    assert (stream["width"], stream["height"]) == (854, 480), probe
    assert Fraction(stream["avg_frame_rate"]) == Fraction(24, 1), probe
    assert float(probe["format"]["duration"]) == pytest.approx(10.0, abs=0.25)

    # Decoding every frame detects container-only signatures and broken media.
    _run([ffmpeg, "-nostdin", "-v", "error", "-i", str(output), "-f", "null", "-"])

    # Repeated requests must not silently allocate a second master for unchanged sources.
    again = service.assemble_project_master(
        project.id,
        requests.AssembleMasterRequest(
            expected_revision=project.revision, ffmpeg_path=ffmpeg,
        ),
    )
    assert again["id"] == master["id"]
    assert len(storage.list_video_records("video_master")) == 1
    # Probe evidence is local to this test; production metadata must not
    # falsely advertise externally validated output without a server probe.
    assert master["actual_video_probe_verified"] is False
