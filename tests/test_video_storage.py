from __future__ import annotations

import importlib

import pytest
from pydantic import ValidationError


VALID_ID = "0123456789abcdef0123456789abcdef"


def models():
    return importlib.import_module("app.video.models")


def storage():
    return importlib.import_module("app.video.storage")


def test_video_asset_path_accepts_supported_extensions(tmp_path, monkeypatch):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    module = storage()

    assert module.video_asset_path(VALID_ID, "png") == tmp_path / "video-assets" / f"{VALID_ID}.png"
    assert module.video_asset_path(VALID_ID, "mp4") == tmp_path / "video-assets" / f"{VALID_ID}.mp4"
    assert module.video_asset_path(VALID_ID, "json") == tmp_path / "video-assets" / f"{VALID_ID}.json"


@pytest.mark.parametrize(
    ("identifier", "extension"),
    [
        ("../escape", "mp4"),
        ("A" * 32, "mp4"),
        ("abc", "png"),
        (VALID_ID, "glb"),
        (VALID_ID, "exe"),
    ],
)
def test_video_asset_path_rejects_invalid_ids_and_extensions(tmp_path, monkeypatch, identifier, extension):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    module = storage()

    with pytest.raises(ValueError):
        module.video_asset_path(identifier, extension)


def test_video_asset_path_rejects_symlinked_asset_directory(tmp_path, monkeypatch):
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (tmp_path / "video-assets").symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    module = storage()

    with pytest.raises(ValueError, match="escapes workspace"):
        module.video_asset_path(VALID_ID, "mp4")


def test_video_record_helpers_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    module = storage()

    created = module.put_video_record("video_job", {"status": "queued"}, identifier=VALID_ID)
    assert created == {"id": VALID_ID, "status": "queued"}
    assert module.get_video_record("video_job", VALID_ID) == created
    assert module.list_video_records("video_job") == [created]

    with pytest.raises(ValueError):
        module.put_video_record("not-video", {})


def test_video_generation_request_normalizes_prompt_and_accepts_valid_values():
    request = models().VideoGenerationRequest(
        image_id=VALID_ID,
        prompt="  slow camera push toward subject  ",
        engine_profile="balanced",
        seed=42,
        duration_seconds=5,
        fps=24,
        resolution="720p",
        motion_strength=0.4,
        camera_motion="zoom_in",
    )

    assert request.prompt == "slow camera push toward subject"
    assert request.seed == 42


@pytest.mark.parametrize(
    "payload",
    [
        {"image_id": VALID_ID, "prompt": "   "},
        {"image_id": "bad", "prompt": "move"},
        {"image_id": VALID_ID, "prompt": "move", "fps": 0},
        {"image_id": VALID_ID, "prompt": "move", "fps": 61},
        {"image_id": VALID_ID, "prompt": "move", "duration_seconds": 0},
        {"image_id": VALID_ID, "prompt": "move", "duration_seconds": 31},
        {"image_id": VALID_ID, "prompt": "move", "resolution": "4k"},
        {"image_id": VALID_ID, "prompt": "move", "motion_strength": 1.1},
        {"image_id": VALID_ID, "prompt": "move", "camera_motion": "teleport"},
    ],
)
def test_video_generation_request_rejects_invalid_bounds(payload):
    with pytest.raises(ValidationError):
        models().VideoGenerationRequest(**payload)


def test_privacy_preferences_have_shoulder_surfing_defaults():
    prefs = models().PrivacyPreferences()

    assert prefs.model_dump() == {
        "privacy_mode": True,
        "mask_prompts": True,
        "blur_media": True,
        "quick_hide": True,
        "idle_lock_seconds": 30,
        "require_unlock_on_resume": True,
        "neutral_project_names": True,
    }
