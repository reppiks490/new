"""Exercise actual CPU FFmpeg media output when both binaries are installed.

This proves a real, decodable synthetic master; it does NOT prove GPU model
generation, owner hardware readiness or artistic/visual quality.
"""
from __future__ import annotations

import importlib
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="local FFmpeg + ffprobe must both be installed",
)
def test_real_ffmpeg_master_cfr_duration_and_complete_decode(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    storage = importlib.import_module("app.video.storage")
    scenes = []
    for index, frame_rate in enumerate((12, 30)):
        asset_id = f"{300 + index:032x}"
        path = storage.video_asset_path(asset_id, "mp4")
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i",
                f"color=c={'red' if index == 0 else 'blue'}:s=160x90:r={frame_rate}:d=1",
                "-an", "-c:v", "mpeg4", "-q:v", "4", str(path),
            ],
            check=True, capture_output=True, text=True, timeout=45,
        )
        assert path.is_file()
        scenes.append(asset_id)

    project = service.create_project(
        models.ProjectCreateRequest(
            title="Synthetic codec and frame verification",
            master_prompt="A short two-shot synthetic video. No external models.",
            target_duration_seconds=10,
            delivery_fps=24,
            delivery_resolution="480p",
            aspect_ratio="16:9",
        )
    )
    shot_models = [
        models.CinematicShot(
            shot_id=f"{400 + index:032x}", ordinal=index + 1,
            title=f"Scene {index + 1}", prompt=f"Short scene {index + 1}",
            duration_seconds=1.0,
        )
        for index in range(2)
    ]
    scene = models.CinematicScene(
        scene_id="2" * 32, ordinal=1, title="Timeline",
        target_duration_seconds=2, shots=shot_models,
    )
    project = service.update_project(
        project.id, models.ProjectUpdateRequest(expected_revision=1, scenes=[scene]),
    )
    linked = []
    for shot, asset_id in zip(project.scenes[0].shots, scenes):
        record = storage.put_video_record(
            "video_job", {
                "status": "succeeded", "project_id": project.id,
                "scene_id": scene.scene_id, "shot_id": shot.shot_id,
                "project_revision": project.revision, "asset_id": asset_id,
                "asset_url": f"/api/video/assets/{asset_id}.mp4",
            },
        )
        linked.append(shot.model_copy(update={"latest_job_id": record["id"]}))
    project = service.update_project(
        project.id,
        models.ProjectUpdateRequest(
            expected_revision=2, scenes=[scene.model_copy(update={"shots": linked})],
        ),
    )
    request = importlib.import_module("app.video.cinematic_requests")
    result = service.assemble_project_master(
        project.id, request.AssembleMasterRequest(expected_revision=project.revision),
    )
    assert result["actual_video_probe_verified"] is True
    assert result["probe"]["codec"] == "h264"
    assert result["probe"]["fps"] == "24"
    assert result["probe"]["frame_count"] == 48
    assert result["probe"]["duration_seconds"] == pytest.approx(2.0, abs=0.05)
    assert result["timeline_seconds"] == 2.0
    assert len(result["source_asset_hashes"]) == 2
    output = storage.video_asset_path(result["asset_id"], "mp4")
    assert output.is_file() and output.stat().st_size > 1000

    # Decode the whole synthetic output, not only its container metadata.
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(output),
         "-an", "-f", "null", "-"],
        check=True, capture_output=True, text=True, timeout=45,
    )
    # A second assembly with the same inputs must reuse the hashed artifact.
    again = service.assemble_project_master(
        project.id, request.AssembleMasterRequest(expected_revision=project.revision),
    )
    assert again["asset_id"] == result["asset_id"]
