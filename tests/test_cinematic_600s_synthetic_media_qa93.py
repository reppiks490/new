"""QA93: opt-in full 600-second local synthetic master acceptance.

Exercises the actual cinematic assembly path with 60 ordered ten-second shots
and real CPU FFmpeg/FFprobe. Source MP4s are generated locally from two colors;
no model inference, owner media, mobile hardware, or paid services are involved.

The environment gate prevents this long-running acceptance from silently
inflating every general CI run. Dedicated QA93 workflow explicitly enables it.
"""
from __future__ import annotations

import hashlib
import importlib
import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(
    os.environ.get("CINEMATIC_LONGFORM_MEDIA_QA") != "1",
    reason="600-second synthetic FFmpeg acceptance is opt-in",
)
def test_600_second_master_60_shots_real_ffmpeg(monkeypatch, tmp_path: Path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.fail("Dedicated long-form media acceptance requires ffmpeg and ffprobe")
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))

    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    storage = importlib.import_module("app.video.storage")
    requests = importlib.import_module("app.video.cinematic_requests")

    assets = []
    for index, color in enumerate(("red", "blue")):
        asset_id = f"{100 + index:032x}"
        path = storage.video_asset_path(asset_id, "mp4")
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", f"color=c={color}:s=160x90:r=24:d=1",
                "-an", "-c:v", "mpeg4", "-q:v", "4", str(path),
            ],
            check=True, capture_output=True, text=True, timeout=90,
        )
        assert path.is_file() and path.stat().st_size > 1000
        assets.append(asset_id)

    project = service.create_project(
        models.ProjectCreateRequest(
            title="QA93 synthetic 600-second ordered film",
            master_prompt="Synthetic colored frames for local duration QA only.",
            target_duration_seconds=600,
            delivery_fps=24,
            delivery_resolution="480p",
            aspect_ratio="16:9",
        )
    )
    shots = [
        models.CinematicShot(
            shot_id=f"{1000 + index:032x}",
            ordinal=index + 1,
            title=f"Synthetic shot {index + 1}",
            prompt="Local color frames, no inference.",
            duration_seconds=10.0,
        )
        for index in range(60)
    ]
    scene = models.CinematicScene(
        scene_id="2" * 32, ordinal=1, title="Long-form sequence",
        target_duration_seconds=600, shots=shots,
    )
    project = service.update_project(
        project.id,
        models.ProjectUpdateRequest(expected_revision=1, scenes=[scene]),
    )
    linked = []
    for index, shot in enumerate(project.scenes[0].shots):
        asset_id = assets[index % 2]
        record = storage.put_video_record(
            "video_job", {
                "status": "succeeded",
                "project_id": project.id,
                "scene_id": scene.scene_id,
                "shot_id": shot.shot_id,
                "project_revision": project.revision,
                "asset_id": asset_id,
                "asset_url": f"/api/video/assets/{asset_id}.mp4",
            },
        )
        linked.append(shot.model_copy(update={"latest_job_id": record["id"]}))
    project = service.update_project(
        project.id,
        models.ProjectUpdateRequest(
            expected_revision=2,
            scenes=[scene.model_copy(update={"shots": linked})],
        ),
    )

    # QA94 diagnostic only: surface FFmpeg's synthetic-media stderr if the
    # actual application command fails. Production code still builds/runs the
    # unmodified command; no command flags or runtime behavior are changed.
    original_ffmpeg_runner = service._run_master_ffmpeg

    def _diagnostic_ffmpeg_runner(command, **kwargs):
        execution = original_ffmpeg_runner(command, **kwargs)
        if execution.returncode != 0:
            stderr = execution.stderr if isinstance(execution.stderr, str) else ""
            raise RuntimeError(
                f"Synthetic QA FFmpeg returned {execution.returncode}; "
                f"stderr tail: {stderr[-1800:]}"
            )
        return execution

    monkeypatch.setattr(service, "_run_master_ffmpeg", _diagnostic_ffmpeg_runner)

    result = service.assemble_project_master(
        project.id,
        requests.AssembleMasterRequest(expected_revision=project.revision),
    )
    assert result["status"] == "ready"
    assert result["actual_video_probe_verified"] is True
    assert result["source_shot_count"] == 60
    assert result["timeline_frames"] == 14_400
    assert result["timeline_seconds"] == pytest.approx(600.0)
    assert result["probe"]["codec"] == "h264"
    assert result["probe"]["fps"] == "24"
    assert result["probe"]["frame_count"] == 14_400
    assert result["probe"]["duration_seconds"] == pytest.approx(600.0, abs=0.05)

    output = storage.video_asset_path(result["asset_id"], "mp4")
    assert output.is_file() and output.stat().st_size > 1000
    with output.open("rb") as handle:
        assert hashlib.file_digest(handle, "sha256").hexdigest() == result["sha256"]

    # Decode every output frame; metadata alone cannot establish decodability.
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-v", "error", "-xerror",
            "-i", str(output), "-an", "-f", "null", "-",
        ],
        check=True, capture_output=True, text=True, timeout=600,
    )

    # Check both ends of the 600-second sequence, not merely the container.
    def sampled_rgb(second: int) -> bytes:
        frame = subprocess.run(
            [
                "ffmpeg", "-nostdin", "-v", "error", "-ss", str(second),
                "-i", str(output), "-frames:v", "1", "-vf", "scale=1:1",
                "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
            ],
            check=True, capture_output=True, timeout=90,
        ).stdout
        assert len(frame) == 3
        return frame

    first, last = sampled_rgb(5), sampled_rgb(595)
    assert first[0] > first[2] + 50, "First synthetic shot must be red"
    assert last[2] > last[0] + 50, "Last synthetic shot must be blue"

    # A second request must reuse the verified SHA-linked artifact.
    again = service.assemble_project_master(
        project.id,
        requests.AssembleMasterRequest(expected_revision=project.revision),
    )
    assert again["asset_id"] == result["asset_id"]
