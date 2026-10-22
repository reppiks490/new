from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from PIL import Image

A = "0" * 32
SCENE = "2" * 32
SHOT = "3" * 32


def _ready_project(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    storage = importlib.import_module("app.video.storage")
    Image.new("RGB", (24, 16), (12, 34, 56)).save(storage.video_asset_path(A, "png"))
    created = service.create_project(
        models.ProjectCreateRequest(
            title="Render Test",
            master_prompt="MASTER_SENTINEL_DO_NOT_STORE " + ("world " * 500),
            target_duration_seconds=600,
            delivery_fps=120,
            delivery_resolution="2160p",
            aspect_ratio="16:9",
            continuity_bible={"wardrobe": "black coat", "weather": "rain", "lighting": "moonlight"},
            reference_image_ids=[A],
        )
    )
    shot = models.CinematicShot(
        shot_id=SHOT,
        ordinal=1,
        title="Close-up",
        prompt=("She slowly turns toward the camera while keeping exact facial identity. " * 35).strip(),
        duration_seconds=5,
        continuity_patch={"wardrobe": "red coat", "freeform_notes": {"mood": "urgent"}},
    )
    scene = models.CinematicScene(
        scene_id=SCENE,
        ordinal=1,
        title="Rooftop",
        source_text="She turns.",
        target_duration_seconds=5,
        continuity_patch={"weather": "heavy rain"},
        shots=[shot],
    )
    project = service.update_project(
        created.id,
        models.ProjectUpdateRequest(expected_revision=1, scenes=[scene]),
    )
    return models, service, storage, project


def test_pack_engine_prompt_is_deterministic_local_and_bounded(monkeypatch, tmp_path):
    models, service, _, project = _ready_project(monkeypatch, tmp_path)
    scene = project.scenes[0]
    shot = scene.shots[0]
    plan = models.RenderPlan(
        project_id=project.id,
        project_revision=project.revision,
        scene_id=scene.scene_id,
        shot_id=shot.shot_id,
        engine_name="fake",
        engine_profile="balanced",
        prompt=shot.prompt,
        effective_continuity=service.resolve_effective_continuity(project, scene, shot),
        reference_image_ids=[A],
        source_image_id=A,
        duration_seconds=5,
        seed=0,
        generation_fps=60,
        generation_resolution="1080p",
        delivery_fps=120,
        delivery_resolution="2160p",
    )
    first = service.pack_engine_prompt(plan, max_chars=2000)
    second = service.pack_engine_prompt(plan, max_chars=2000)
    assert first == second
    assert len(first) <= 2000
    assert "She slowly turns toward the camera" in first
    assert "MASTER_SENTINEL_DO_NOT_STORE" not in first
    assert "red coat" in first
    assert "heavy rain" in first


def test_render_shot_records_opaque_job_link_without_prompt_leak(monkeypatch, tmp_path):
    models, service, storage, project = _ready_project(monkeypatch, tmp_path)
    engine = importlib.import_module("app.video.engine")
    jobs = importlib.import_module("app.video.jobs")
    requests = importlib.import_module("app.video.cinematic_requests")
    engine._ENGINE_REGISTRY.clear()
    engine.register_engine(engine.FakeVideoEngine())

    submitted = []
    class CapturePool:
        def submit(self, fn, *args, **kwargs):
            submitted.append((fn, args, kwargs))
            return object()
    monkeypatch.setattr(jobs, "pool", CapturePool())

    result = service.render_shot(
        project.id,
        SCENE,
        SHOT,
        requests.ShotRenderRequest(expected_revision=2, engine_name="fake"),
    )
    assert result["job"]["id"]
    assert result["project"]["revision"] == 3
    refreshed = service.get_project(project.id)
    stored_shot = refreshed.scenes[0].shots[0]
    assert stored_shot.latest_job_id == result["job"]["id"]
    assert stored_shot.latest_rendered_project_revision == 2

    record = storage.get_video_record("video_job", result["job"]["id"])
    assert record["project_id"] == project.id
    assert record["scene_id"] == SCENE
    assert record["shot_id"] == SHOT
    assert record["project_revision"] == 2
    assert "prompt" not in record
    assert "MASTER_SENTINEL_DO_NOT_STORE" not in str(record)
    assert 1 <= record["prompt_chars"] <= 2000
    assert len(submitted) == 1


def test_render_stale_revision_rejected_before_job_created(monkeypatch, tmp_path):
    _, service, storage, project = _ready_project(monkeypatch, tmp_path)
    requests = importlib.import_module("app.video.cinematic_requests")
    before = list(storage.list_video_records("video_job"))
    with pytest.raises(service.ProjectRevisionConflict):
        service.render_shot(
            project.id,
            SCENE,
            SHOT,
            requests.ShotRenderRequest(expected_revision=1, engine_name="fake"),
        )
    after = list(storage.list_video_records("video_job"))
    assert after == before


def test_render_missing_reference_rejected_before_job_created(monkeypatch, tmp_path):
    models, service, storage, project = _ready_project(monkeypatch, tmp_path)
    storage.video_asset_path(A, "png").unlink()
    requests = importlib.import_module("app.video.cinematic_requests")
    before = list(storage.list_video_records("video_job"))
    with pytest.raises(FileNotFoundError):
        service.render_shot(
            project.id,
            SCENE,
            SHOT,
            requests.ShotRenderRequest(expected_revision=project.revision, engine_name="fake"),
        )
    assert list(storage.list_video_records("video_job")) == before
