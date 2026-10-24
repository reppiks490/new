"""QA39: a shot's ftyp header is not evidence that its video can decode.

Actual application storage/status + genuine synthetic FFmpeg media. Strict
production-contract assertion is opt-in until lead integrates source validation.
No model inference, owner footage, GPU, or cloud services.
"""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

STRICT = os.getenv("CINEMATIC_REQUIRE_SHOT_SOURCE_DECODE_QA39") == "1"
SCENE_ID = "2" * 32
SHOT_ID = "3" * 32
ASSET_ID = "4" * 32


def _tools():
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        if STRICT:
            pytest.fail("Strict QA39 requires FFmpeg and FFprobe")
        pytest.skip("FFmpeg and FFprobe unavailable")
    return ffmpeg, ffprobe


def _run(*args):
    return subprocess.run(
        list(args), capture_output=True, check=False, timeout=90,
    )


@pytest.fixture
def ready_shot(monkeypatch, tmp_path: Path):
    ffmpeg, ffprobe = _tools()
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path / "studio"))
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    storage = importlib.import_module("app.video.storage")
    jobs = importlib.import_module("app.video.jobs")

    project = service.create_project(models.ProjectCreateRequest(
        title="Synthetic decode acceptance",
        master_prompt="SYNTHETIC_PRIVATE_PROMPT_DO_NOT_ECHO",
        target_duration_seconds=10, delivery_fps=24,
        delivery_resolution="480p", aspect_ratio="16:9",
    ))
    shot = models.CinematicShot(
        shot_id=SHOT_ID, ordinal=1, title="Synthetic shot",
        prompt="Synthetic test source", duration_seconds=1,
    )
    scene = models.CinematicScene(
        scene_id=SCENE_ID, ordinal=1, title="Synthetic scene",
        target_duration_seconds=1, shots=[shot],
    )
    project = service.update_project(
        project.id,
        models.ProjectUpdateRequest(expected_revision=1, scenes=[scene]),
    )

    path = storage.video_asset_path(ASSET_ID, "mp4")
    encoded = _run(
        ffmpeg, "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc2=s=160x90:r=24:d=1",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(path),
    )
    assert encoded.returncode == 0, "Synthetic FFmpeg encode failed"
    assert _run(ffprobe, "-v", "error", "-show_streams", str(path)).returncode == 0
    assert _run(
        ffmpeg, "-nostdin", "-v", "error", "-xerror",
        "-i", str(path), "-map", "0:v:0", "-an", "-f", "null", "-",
    ).returncode == 0

    record = storage.put_video_record("video_job", {
        "status": "succeeded", "project_id": project.id,
        "scene_id": SCENE_ID, "shot_id": SHOT_ID,
        "asset_id": ASSET_ID, "project_revision": project.revision,
    })
    linked = shot.model_copy(update={"latest_job_id": record["id"]})
    project = service.update_project(
        project.id, models.ProjectUpdateRequest(
            expected_revision=project.revision,
            scenes=[scene.model_copy(update={"shots": [linked]})],
        ),
    )
    return service, jobs, project, path, ffmpeg, ffprobe


def test_genuine_synthetic_decodable_shot_is_ready(ready_shot):
    service, jobs, project, path, _, _ = ready_shot
    assert jobs._valid_mp4(path)
    status = service.project_render_status(project.id)
    assert status["ready_for_assembly"] is True
    assert status["missing_output_assets"] == 0
    assert status["succeeded"] == 1
    assert "SYNTHETIC_PRIVATE_PROMPT" not in str(status)


@pytest.mark.skipif(
    not STRICT,
    reason="Expected-red production contract runs only in dedicated QA39 workflow",
)
def test_truncated_ftyp_shot_must_not_be_reported_assembly_ready(ready_shot):
    service, jobs, project, path, ffmpeg, ffprobe = ready_shot
    # Retain a genuine MP4 header while removing the rest of a previously
    # fully decodable synthetic source. This is not a mock ffprobe response.
    path.write_bytes(path.read_bytes()[:64])
    assert path.stat().st_size == 64
    assert jobs._valid_mp4(path) is True  # Current 64-byte signature-only gate.
    const_probe = _run(\n        ffprobe, "-v", "error", "-select_streams", "v:0",\n        "-show_entries", "stream=codec_type", "-of", "json", str(path),\n    )\n    # Some FFprobe builds exit zero even when a truncated MP4 has no streams.\n    stream_info = json.loads(const_probe.stdout or b"{}") if const_probe.returncode == 0 else {}\n    assert not any(\n        stream.get("codec_type") == "video"\n        for stream in stream_info.get("streams", [])\n    )
    assert _run(
        ffmpeg, "-nostdin", "-v", "error", "-xerror",
        "-i", str(path), "-an", "-f", "null", "-",
    ).returncode != 0

    status = service.project_render_status(project.id)
    assert status["ready_for_assembly"] is False, (
        "A header-only, undecodable shot was promoted to master-assembly readiness"
    )
    assert status["missing_output_assets"] == 1
    assert "SYNTHETIC_PRIVATE_PROMPT" not in str(status)
