"""Strict RED application contract for unbounded aspect ratios (QA29).

Uses real project create/update/storage logic, not mocked routing or FFmpeg.
The current service accepts a ratio that produces a ~480-trillion-pixel-wide
480p frame; it should reject this before persistence or local FFmpeg launch.
The safe helper in cinematic_geometry_guard_qa29.py is NOT integrated.
"""
from __future__ import annotations

import os

import pytest

from app.video import cinematic_service as service
from app.video.cinematic_models import ProjectCreateRequest, ProjectUpdateRequest


pytestmark = pytest.mark.skipif(
    os.environ.get("CINEMATIC_REQUIRE_EXTREME_GEOMETRY_QA") != "1",
    reason="Strict expected-RED application contract; opt in on dedicated CI",
)

EXTREME_ASPECT = "999999999999:1"


def test_extreme_width_is_rejected_before_project_creation(monkeypatch, tmp_path):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    # This 14-character value is accepted by the current request schema.
    # The current _master_size math yields 479999999999520 x 480 pixels.
    with pytest.raises(ValueError):
        service.create_project(ProjectCreateRequest(
            title="Synthetic geometry", master_prompt="Synthetic, no inference",
            target_duration_seconds=10, delivery_resolution="480p",
            aspect_ratio=EXTREME_ASPECT,
        ))
    assert service.list_projects() == []


def test_extreme_width_update_rejected_without_revision_change(monkeypatch, tmp_path):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    project = service.create_project(ProjectCreateRequest(
        title="Synthetic geometry", master_prompt="Synthetic, no inference",
        target_duration_seconds=10, delivery_resolution="480p",
        aspect_ratio="16:9",
    ))
    with pytest.raises(ValueError):
        service.update_project(project.id, ProjectUpdateRequest(
            expected_revision=project.revision,
            aspect_ratio=EXTREME_ASPECT,
        ))
    persisted = service.get_project(project.id)
    assert persisted.revision == project.revision
    assert persisted.aspect_ratio == "16:9"
