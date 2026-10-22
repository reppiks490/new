from __future__ import annotations

from datetime import datetime, timezone
import importlib
from pathlib import Path

import pytest

A = "0" * 32
C = "2" * 32
D = "3" * 32


def _objects(models, *, delivery_fps=120, delivery_resolution="2160p", duration=5):
    now = datetime.now(timezone.utc)
    shot = models.CinematicShot(
        shot_id=D,
        ordinal=1,
        title="Close-up",
        prompt="She turns toward camera while rain moves naturally across the frame.",
        duration_seconds=duration,
        reference_image_ids=[A],
        continuity_patch={"wardrobe": "red coat"},
    )
    scene = models.CinematicScene(
        scene_id=C,
        ordinal=1,
        title="Rooftop",
        source_text="She turns toward camera.",
        target_duration_seconds=duration,
        continuity_patch={"weather": "rain"},
        shots=[shot],
    )
    project = models.CinematicProject(
        id="f" * 32,
        revision=7,
        title="Film",
        master_prompt="MASTER_SENTINEL_DO_NOT_COPY_TO_SHOTS " + ("world building " * 500),
        target_duration_seconds=600,
        delivery_fps=delivery_fps,
        delivery_resolution=delivery_resolution,
        aspect_ratio="16:9",
        continuity_bible={"wardrobe": "black coat", "lighting": "moonlight"},
        reference_image_ids=[A],
        scenes=[scene],
        created_at=now,
        updated_at=now,
    )
    return project, scene, shot


def _caps(video_models, *, fps=None, resolutions=None, max_duration=30):
    return video_models.EngineCapabilities(
        name="fixture",
        available=True,
        profiles=["low_vram", "balanced", "high_quality"],
        supported_resolutions=resolutions or ["480p", "720p", "1080p"],
        min_duration_seconds=1,
        max_duration_seconds=max_duration,
        supported_fps=fps or [8, 12, 24, 30, 60],
        supports_motion_strength=True,
        camera_motion_presets=["static", "orbit"],
    )


def test_2160p_120_delivery_negotiates_to_1080p_60_engine_native():
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    video_models = importlib.import_module("app.video.models")
    project, scene, shot = _objects(models)
    plan = service.build_render_plan_from_objects(project, scene, shot, _caps(video_models), require_assets=False)
    assert plan.generation_resolution == "1080p"
    assert plan.generation_fps == 60
    assert plan.delivery_resolution == "2160p"
    assert plan.delivery_fps == 120


def test_1080p_24_delivery_uses_1080p_24_when_supported():
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    video_models = importlib.import_module("app.video.models")
    project, scene, shot = _objects(models, delivery_fps=24, delivery_resolution="1080p")
    plan = service.build_render_plan_from_objects(project, scene, shot, _caps(video_models), require_assets=False)
    assert plan.generation_resolution == "1080p"
    assert plan.generation_fps == 24


def test_plan_contains_local_shot_text_and_continuity_but_not_master_prompt():
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    video_models = importlib.import_module("app.video.models")
    project, scene, shot = _objects(models)
    plan = service.build_render_plan_from_objects(project, scene, shot, _caps(video_models), require_assets=False)
    assert "She turns toward camera" in plan.prompt
    assert "MASTER_SENTINEL_DO_NOT_COPY_TO_SHOTS" not in plan.prompt
    assert plan.effective_continuity.wardrobe == "red coat"
    assert plan.effective_continuity.weather == "rain"
    assert plan.effective_continuity.lighting == "moonlight"


def test_plan_rejects_missing_reference_before_queueing(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    video_models = importlib.import_module("app.video.models")
    project, scene, shot = _objects(models)
    with pytest.raises(FileNotFoundError):
        service.build_render_plan_from_objects(project, scene, shot, _caps(video_models), require_assets=True)


def test_plan_does_not_silently_truncate_overlong_shot():
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    video_models = importlib.import_module("app.video.models")
    project, scene, shot = _objects(models, duration=12)
    with pytest.raises(ValueError, match="duration"):
        service.build_render_plan_from_objects(
            project,
            scene,
            shot,
            _caps(video_models, max_duration=10),
            require_assets=False,
        )


def test_native_selection_uses_engine_minimum_when_delivery_is_below_all_supported_values():
    service = importlib.import_module("app.video.cinematic_service")
    assert service.select_native_fps(1, [8, 12, 24]) == 8
    assert service.select_native_resolution("480p", ["720p", "1080p"]) == "720p"
