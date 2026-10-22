from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from app.video.cinematic_capability_preflight import audit_engine_capabilities
from app.video.cinematic_models import CinematicProject, CinematicScene, CinematicShot
from app.video.engine import FakeVideoEngine

REF = "a" * 32


def _project(*, delivery_fps=24, delivery_resolution="1080p", shots=2):
    now = datetime.now(timezone.utc)
    cinematic_shots = [
        CinematicShot(
            shot_id=f"{index + 100:032x}",
            ordinal=index + 1,
            title="Secret shot",
            prompt="DO NOT EXPOSE MY PRIVATE PROMPT",
            duration_seconds=5,
        )
        for index in range(shots)
    ]
    return CinematicProject(
        id="f" * 32,
        revision=7,
        title="Secret film",
        master_prompt="MASTER_PRIVATE",
        target_duration_seconds=max(10, shots * 5),
        delivery_fps=delivery_fps,
        delivery_resolution=delivery_resolution,
        aspect_ratio="16:9",
        reference_image_ids=[REF],
        continuity_bible={"freeform_notes": {"private": "hide this value"}},
        scenes=[
            CinematicScene(
                scene_id="1" * 32,
                ordinal=1,
                title="Hidden scene",
                target_duration_seconds=max(1, shots * 5),
                shots=cinematic_shots,
            )
        ],
        created_at=now,
        updated_at=now,
    )


def _codes(report):
    return [finding.code for finding in report.findings]


def test_compatible_engine_with_exact_native_delivery_is_ready():
    report = audit_engine_capabilities(_project(), FakeVideoEngine().capabilities())
    assert report.capability_ready
    assert report.shot_count == 2
    assert report.compatible_shots == 2
    assert report.selected_native_fps == 24
    assert report.selected_native_resolution == "1080p"
    assert report.findings == ()


def test_high_delivery_format_is_not_misrepresented_as_native_generation():
    report = audit_engine_capabilities(
        _project(delivery_fps=120, delivery_resolution="2160p"),
        FakeVideoEngine().capabilities(),
    )
    assert report.capability_ready
    assert report.selected_native_fps == 60
    assert report.selected_native_resolution == "1080p"
    assert _codes(report) == [
        "DELIVERY_FPS_REQUIRES_FINISHING",
        "DELIVERY_RESOLUTION_REQUIRES_FINISHING",
    ]


def test_unsupported_controls_are_shot_scoped_and_block_compatibility():
    project = _project()
    first, second = project.scenes[0].shots
    first.motion_strength = 0.5
    first.camera_motion = "orbit"
    second.engine_profile = "high_quality"
    second.duration_seconds = 0.5  # allowed by CinematicShot, not VideoGenerationRequest
    capabilities = FakeVideoEngine().capabilities().model_copy(
        update={"profiles": ["balanced"]}
    )
    report = audit_engine_capabilities(project, capabilities)
    assert not report.capability_ready
    assert report.compatible_shots == 0
    assert _codes(report) == [
        "SHOT_MOTION_STRENGTH_UNSUPPORTED",
        "SHOT_CAMERA_MOTION_UNSUPPORTED",
        "SHOT_PROFILE_UNSUPPORTED",
        "SHOT_DURATION_UNSUPPORTED",
    ]
    assert report.findings[0].shot_id == first.shot_id
    assert report.findings[-1].shot_id == second.shot_id


def test_unavailable_engine_is_not_falsely_ready_even_if_controls_match():
    cap = FakeVideoEngine().capabilities().model_copy(update={"available": False})
    report = audit_engine_capabilities(_project(), cap)
    assert not report.capability_ready
    assert report.compatible_shots == 0
    assert _codes(report) == ["ENGINE_UNAVAILABLE"]


@pytest.mark.parametrize(
    ("update", "expected_code"),
    [
        ({"supported_fps": []}, "ENGINE_FPS_DECLARATION_INVALID"),
        ({"supported_resolutions": []}, "ENGINE_RESOLUTION_DECLARATION_INVALID"),
        ({"min_duration_seconds": 10.0, "max_duration_seconds": 2.0},
         "ENGINE_DURATION_DECLARATION_INVALID"),
        ({"supported_fps": [120]}, "NATIVE_FPS_EXCEEDS_REQUEST_MODEL"),
        ({"supported_resolutions": ["2160p"]}, "ENGINE_RESOLUTION_DECLARATION_INVALID"),
    ],
)
def test_incompatible_capability_declarations_are_safe_errors(update, expected_code):
    cap = FakeVideoEngine().capabilities().model_copy(update=update)
    project = _project(delivery_fps=120, delivery_resolution="2160p")
    report = audit_engine_capabilities(project, cap)
    assert not report.capability_ready
    assert expected_code in _codes(report)
    assert report.compatible_shots == 0


def test_delivery_below_engine_native_minimum_is_explicitly_reported():
    cap = FakeVideoEngine().capabilities().model_copy(
        update={"supported_fps": [30, 60], "supported_resolutions": ["720p", "1080p"]}
    )
    report = audit_engine_capabilities(
        _project(delivery_fps=10, delivery_resolution="480p"), cap,
    )
    assert report.capability_ready
    assert report.selected_native_fps == 30
    assert report.selected_native_resolution == "720p"
    assert _codes(report) == ["NATIVE_FPS_ABOVE_DELIVERY", "NATIVE_RESOLUTION_ABOVE_DELIVERY"]


def test_zero_shot_project_does_not_claim_capability_ready():
    project = _project(shots=0)
    report = audit_engine_capabilities(project, FakeVideoEngine().capabilities())
    assert not report.capability_ready
    assert report.shot_count == report.compatible_shots == 0


def test_data_minimization_no_engine_detail_camera_or_prompt_leakage():
    project = _project()
    project.scenes[0].shots[0].camera_motion = "private_camera_setting"
    cap = FakeVideoEngine().capabilities().model_copy(
        update={"detail": "PRIVATE ENGINE INTERNALS", "name": "DO NOT DISCLOSE ENGINE"}
    )
    before = project.model_dump(mode="json")
    one = audit_engine_capabilities(project, cap)
    two = audit_engine_capabilities(project, cap)
    payload = json.dumps(one.as_dict())
    for forbidden in (
        "PRIVATE ENGINE INTERNALS", "DO NOT DISCLOSE ENGINE", "private_camera_setting",
        "DO NOT EXPOSE MY PRIVATE PROMPT", "MASTER_PRIVATE", "Secret film", "hide this value",
    ):
        assert forbidden not in payload
    assert one == two
    assert project.model_dump(mode="json") == before


def test_capability_scan_scales_to_hundreds_of_shots_without_truncation():
    project = _project(shots=480)
    report = audit_engine_capabilities(project, FakeVideoEngine().capabilities())
    assert report.capability_ready
    assert report.shot_count == 480
    assert report.compatible_shots == 480
