from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import importlib
from pathlib import Path
import threading

import pytest

A = "0" * 32
B = "1" * 32
C = "2" * 32
D = "3" * 32


def _create_request(models, title="Film"):
    return models.ProjectCreateRequest(
        title=title,
        master_prompt="SCENE 1: Start\nA character enters.",
        target_duration_seconds=600,
        delivery_fps=120,
        delivery_resolution="2160p",
        aspect_ratio="16:9",
        continuity_bible={"wardrobe": "black coat", "weather": "rain"},
        reference_image_ids=[],
    )


def test_create_read_list_project(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    created = service.create_project(_create_request(models))
    assert created.id and len(created.id) == 32
    assert created.revision == 1
    assert service.get_project(created.id).title == "Film"
    assert [item.id for item in service.list_projects()] == [created.id]


def test_successful_update_increments_revision(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    created = service.create_project(_create_request(models))
    updated = service.update_project(
        created.id,
        models.ProjectUpdateRequest(expected_revision=1, title="Renamed"),
    )
    assert updated.title == "Renamed"
    assert updated.revision == 2


def test_stale_expected_revision_raises_conflict_and_does_not_write(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    created = service.create_project(_create_request(models))
    service.update_project(created.id, models.ProjectUpdateRequest(expected_revision=1, title="Winner"))
    with pytest.raises(service.ProjectRevisionConflict):
        service.update_project(created.id, models.ProjectUpdateRequest(expected_revision=1, title="Loser"))
    stored = service.get_project(created.id)
    assert stored.title == "Winner"
    assert stored.revision == 2


def test_simultaneous_updates_allow_exactly_one_winner(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    created = service.create_project(_create_request(models))
    barrier = threading.Barrier(2)

    def attempt(title):
        barrier.wait(timeout=5)
        try:
            result = service.update_project(
                created.id,
                models.ProjectUpdateRequest(expected_revision=1, title=title),
            )
            return ("ok", result.title)
        except service.ProjectRevisionConflict:
            return ("conflict", title)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, ["Alpha", "Beta"]))
    assert sorted(status for status, _ in outcomes) == ["conflict", "ok"]
    stored = service.get_project(created.id)
    assert stored.revision == 2
    assert stored.title in {"Alpha", "Beta"}


def test_project_scene_shot_continuity_merges_in_order():
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    now = datetime.now(timezone.utc)
    shot = models.CinematicShot(
        shot_id=D,
        ordinal=1,
        title="Close",
        prompt="She turns.",
        duration_seconds=5,
        continuity_patch={"wardrobe": "red coat", "freeform_notes": {"mood": "urgent"}},
    )
    scene = models.CinematicScene(
        scene_id=C,
        ordinal=1,
        title="Street",
        source_text="She turns.",
        target_duration_seconds=5,
        continuity_patch={"weather": "snow", "freeform_notes": {"camera": "handheld"}},
        shots=[shot],
    )
    project = models.CinematicProject(
        revision=1,
        title="Continuity",
        master_prompt="She turns.",
        target_duration_seconds=10,
        delivery_fps=24,
        delivery_resolution="1080p",
        aspect_ratio="16:9",
        continuity_bible={"wardrobe": "black coat", "weather": "rain", "freeform_notes": {"mood": "cold"}},
        scenes=[scene],
        created_at=now,
        updated_at=now,
    )
    merged = service.resolve_effective_continuity(project, scene, shot)
    assert merged.wardrobe == "red coat"
    assert merged.weather == "snow"
    assert merged.freeform_notes == {"mood": "urgent", "camera": "handheld"}
    assert project.continuity_bible.wardrobe == "black coat"


def test_reference_resolution_deduplicates_project_scene_shot_order():
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    now = datetime.now(timezone.utc)
    shot = models.CinematicShot(
        shot_id=D,
        ordinal=1,
        title="Shot",
        prompt="Move.",
        duration_seconds=5,
        reference_image_ids=[C, D, A],
    )
    scene = models.CinematicScene(
        scene_id=C,
        ordinal=1,
        title="Scene",
        source_text="Move.",
        target_duration_seconds=5,
        reference_image_ids=[B, C],
        shots=[shot],
    )
    project = models.CinematicProject(
        revision=1,
        title="Refs",
        master_prompt="Move.",
        target_duration_seconds=10,
        delivery_fps=24,
        delivery_resolution="1080p",
        aspect_ratio="16:9",
        reference_image_ids=[A, B],
        scenes=[scene],
        created_at=now,
        updated_at=now,
    )
    assert service.resolve_reference_ids(project, scene, shot, require_assets=False) == [A, B, C, D]


def test_missing_reference_asset_is_rejected(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    now = datetime.now(timezone.utc)
    shot = models.CinematicShot(shot_id=D, ordinal=1, title="Shot", prompt="Move.", duration_seconds=5)
    scene = models.CinematicScene(scene_id=C, ordinal=1, title="Scene", source_text="Move.", target_duration_seconds=5, shots=[shot])
    project = models.CinematicProject(
        revision=1,
        title="Missing",
        master_prompt="Move.",
        target_duration_seconds=10,
        delivery_fps=24,
        delivery_resolution="1080p",
        aspect_ratio="16:9",
        reference_image_ids=[A],
        scenes=[scene],
        created_at=now,
        updated_at=now,
    )
    with pytest.raises(FileNotFoundError):
        service.resolve_reference_ids(project, scene, shot, require_assets=True)
