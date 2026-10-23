"""Fail-closed malformed metadata tests for the *read-only* engine audit.

These cases intentionally bypass Pydantic field validation through model_copy.
No GPU, network, user media, generation or paid provider is used.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from app.video.cinematic_capability_preflight import audit_engine_capabilities
from app.video.cinematic_models import CinematicProject, CinematicScene, CinematicShot
from app.video.engine import FakeVideoEngine

REF = "a" * 32


def project():
    now = datetime.now(timezone.utc)
    return CinematicProject(
        id="f" * 32,
        revision=6,
        title="PRIVATE FILM",
        master_prompt="PRIVATE SCRIPT",
        target_duration_seconds=10,
        delivery_fps=24,
        delivery_resolution="1080p",
        aspect_ratio="16:9",
        reference_image_ids=[REF],
        scenes=[
            CinematicScene(
                scene_id="1" * 32,
                ordinal=1,
                title="PRIVATE SCENE",
                target_duration_seconds=10,
                shots=[
                    CinematicShot(
                        shot_id=f"{i + 100:032x}",
                        ordinal=i + 1,
                        title="PRIVATE SHOT",
                        prompt="PRIVATE CHARACTER PROMPT",
                        duration_seconds=5,
                    )
                    for i in range(2)
                ],
            )
        ],
        created_at=now,
        updated_at=now,
    )


def codes(report):
    return [finding.code for finding in report.findings]


@pytest.mark.parametrize(
    ("malformed", "expected"),
    [
        ({"profiles": None}, "ENGINE_PROFILES_DECLARATION_INVALID"),
        ({"profiles": "balanced"}, "ENGINE_PROFILES_DECLARATION_INVALID"),
        ({"profiles": ["PRIVATE_PROVIDER_PROFILE"]}, "ENGINE_PROFILES_DECLARATION_INVALID"),
        ({"profiles": []}, "ENGINE_PROFILES_DECLARATION_INVALID"),
        ({"camera_motion_presets": None}, "ENGINE_CAMERA_PRESETS_DECLARATION_INVALID"),
        ({"camera_motion_presets": "orbit"}, "ENGINE_CAMERA_PRESETS_DECLARATION_INVALID"),
        ({"camera_motion_presets": ["PRIVATE_CAMERA_CONTROL"]}, "ENGINE_CAMERA_PRESETS_DECLARATION_INVALID"),
        ({"supported_fps": 24}, "ENGINE_FPS_DECLARATION_INVALID"),
        ({"supported_fps": "24"}, "ENGINE_FPS_DECLARATION_INVALID"),
        ({"supported_fps": [24, True]}, "ENGINE_FPS_DECLARATION_INVALID"),
        ({"supported_fps": []}, "ENGINE_FPS_DECLARATION_INVALID"),
        ({"supported_resolutions": None}, "ENGINE_RESOLUTION_DECLARATION_INVALID"),
        ({"supported_resolutions": "1080p"}, "ENGINE_RESOLUTION_DECLARATION_INVALID"),
        ({"available": "yes"}, "ENGINE_AVAILABILITY_DECLARATION_INVALID"),
        ({"supports_motion_strength": "yes"}, "ENGINE_MOTION_SUPPORT_DECLARATION_INVALID"),
        ({"min_duration_seconds": "2"}, "ENGINE_DURATION_DECLARATION_INVALID"),
        ({"max_duration_seconds": 10 ** 1000}, "ENGINE_DURATION_DECLARATION_INVALID"),
        ({"max_duration_seconds": float("nan")}, "ENGINE_DURATION_DECLARATION_INVALID"),
    ],
)
def test_malformed_engine_declarations_block_without_crashing_or_disclosing(malformed, expected):
    capability = FakeVideoEngine().capabilities().model_copy(update=malformed)
    report = audit_engine_capabilities(project(), capability)
    assert not report.capability_ready
    assert report.compatible_shots == 0
    assert expected in codes(report)
    payload = json.dumps(report.as_dict())
    assert "PRIVATE" not in payload
    assert "PRIVATE_PROVIDER_PROFILE" not in payload
    assert "PRIVATE_CAMERA_CONTROL" not in payload


@pytest.mark.parametrize(
    ("field", "malformed", "expected"),
    [
        ("delivery_fps", "120", "PROJECT_DELIVERY_FPS_INVALID"),
        ("delivery_fps", True, "PROJECT_DELIVERY_FPS_INVALID"),
        ("delivery_fps", -1, "PROJECT_DELIVERY_FPS_INVALID"),
        ("delivery_fps", 9999, "PROJECT_DELIVERY_FPS_INVALID"),
        ("delivery_resolution", None, "PROJECT_DELIVERY_RESOLUTION_INVALID"),
        ("delivery_resolution", "PRIVATE_RESOLUTION", "PROJECT_DELIVERY_RESOLUTION_INVALID"),
    ],
)
def test_bypassed_project_delivery_fields_fail_closed(field, malformed, expected):
    altered = project().model_copy(update={field: malformed})
    report = audit_engine_capabilities(altered, FakeVideoEngine().capabilities())
    assert not report.capability_ready
    assert report.compatible_shots == 0
    assert expected in codes(report)
    assert "PRIVATE_RESOLUTION" not in json.dumps(report.as_dict())


@pytest.mark.parametrize("malformed", [None, "5", True, float("nan"), float("inf"), 10 ** 1000])
def test_bypassed_shot_duration_is_never_mistaken_for_a_compatible_render(malformed):
    cinematic = project()
    cinematic.scenes[0].shots[0].duration_seconds = malformed
    report = audit_engine_capabilities(cinematic, FakeVideoEngine().capabilities())
    assert not report.capability_ready
    assert report.shot_count == 2
    assert report.compatible_shots == 1
    assert "SHOT_DURATION_UNSUPPORTED" in codes(report)


def test_bad_motion_control_catalog_is_handled_even_when_used_by_a_shot():
    cinematic = project()
    cinematic.scenes[0].shots[0].camera_motion = "orbit"
    capability = FakeVideoEngine().capabilities().model_copy(
        update={"camera_motion_presets": None}
    )
    report = audit_engine_capabilities(cinematic, capability)
    assert not report.capability_ready
    assert "ENGINE_CAMERA_PRESETS_DECLARATION_INVALID" in codes(report)
    assert "SHOT_CAMERA_MOTION_UNSUPPORTED" in codes(report)
    assert report.compatible_shots == 0


def test_valid_empty_camera_catalog_is_not_a_malformed_declaration():
    capability = FakeVideoEngine().capabilities().model_copy(
        update={"camera_motion_presets": []}
    )
    report = audit_engine_capabilities(project(), capability)
    assert report.capability_ready
    assert "ENGINE_CAMERA_PRESETS_DECLARATION_INVALID" not in codes(report)


def test_valid_snapshot_remains_compatible_and_deterministic():
    cinematic = project()
    before = cinematic.model_dump(mode="json")
    caps = FakeVideoEngine().capabilities()
    first = audit_engine_capabilities(cinematic, caps)
    second = audit_engine_capabilities(cinematic, caps)
    assert first == second
    assert first.capability_ready
    assert first.compatible_shots == 2
    assert cinematic.model_dump(mode="json") == before
