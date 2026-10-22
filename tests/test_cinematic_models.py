from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from pydantic import ValidationError

VALID_A = "0" * 32
VALID_B = "1" * 32


def _project_payload(prompt: str = "A quiet rooftop at night") -> dict:
    return {
        "revision": 1,
        "title": "Long Film",
        "master_prompt": prompt,
        "target_duration_seconds": 600,
        "delivery_fps": 120,
        "delivery_resolution": "2160p",
        "aspect_ratio": "16:9",
        "continuity_bible": {},
        "reference_image_ids": [VALID_A],
        "scenes": [],
        "created_at": "2026-10-22T17:00:00Z",
        "updated_at": "2026-10-22T17:00:00Z",
    }


def test_project_accepts_100000_char_prompt_and_rejects_100001():
    models = importlib.import_module("app.video.cinematic_models")
    ok = models.CinematicProject.model_validate(_project_payload("x" * 100_000))
    assert len(ok.master_prompt) == 100_000
    with pytest.raises(ValidationError):
        models.CinematicProject.model_validate(_project_payload("x" * 100_001))


def test_project_rejects_duplicate_scene_or_shot_ids():
    models = importlib.import_module("app.video.cinematic_models")
    shot = {
        "shot_id": VALID_A,
        "ordinal": 1,
        "title": "Shot",
        "prompt": "Move slowly",
        "duration_seconds": 5,
    }
    scene = {
        "scene_id": VALID_A,
        "ordinal": 1,
        "title": "Scene",
        "synopsis": "",
        "source_text": "Move slowly",
        "target_duration_seconds": 10,
        "shots": [shot, {**shot}],
    }
    with pytest.raises(ValidationError):
        models.CinematicProject.model_validate({**_project_payload(), "scenes": [scene]})

    clean_scene = {**scene, "shots": [shot]}
    with pytest.raises(ValidationError):
        models.CinematicProject.model_validate(
            {**_project_payload(), "scenes": [clean_scene, {**clean_scene}]}
        )


def test_shot_duration_must_be_positive():
    models = importlib.import_module("app.video.cinematic_models")
    with pytest.raises(ValidationError):
        models.CinematicShot.model_validate(
            {
                "shot_id": VALID_A,
                "ordinal": 1,
                "title": "bad",
                "prompt": "bad",
                "duration_seconds": 0,
            }
        )


def test_merge_continuity_is_non_mutating_and_child_overrides_parent():
    models = importlib.import_module("app.video.cinematic_models")
    base = models.ContinuityState(
        wardrobe="black coat",
        weather="rain",
        freeform_notes={"camera": "steady", "mood": "cold"},
    )
    patch = models.ContinuityPatch(
        wardrobe="red coat",
        freeform_notes={"mood": "urgent"},
    )
    merged = models.merge_continuity(base, patch)
    assert merged.wardrobe == "red coat"
    assert merged.weather == "rain"
    assert merged.freeform_notes == {"camera": "steady", "mood": "urgent"}
    assert base.wardrobe == "black coat"
    assert base.freeform_notes == {"camera": "steady", "mood": "cold"}


def test_reference_ids_are_deduplicated_in_first_seen_order():
    models = importlib.import_module("app.video.cinematic_models")
    project = models.CinematicProject.model_validate(
        {**_project_payload(), "reference_image_ids": [VALID_A, VALID_B, VALID_A, VALID_B]}
    )
    assert project.reference_image_ids == [VALID_A, VALID_B]


def test_video_project_storage_kind_round_trips(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    storage = importlib.import_module("app.video.storage")
    stored = storage.put_video_record("video_project", {"revision": 1, "title": "Film"})
    loaded = storage.get_video_record("video_project", stored["id"])
    assert loaded["revision"] == 1
    assert loaded["title"] == "Film"
