"""Acceptance tests for the Helper 2 unified preflight dossier.

No paid API, video inference, FFmpeg, network traffic, or real owner data.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json

from PIL import Image

from app.video.cinematic_models import CinematicProject, CinematicScene, CinematicShot
from app.video.cinematic_preflight_dossier import audit_project_preflight
from app.video.engine import FakeVideoEngine

REF = "a" * 32


def _project(*, shots=2, refs=None, fps=24, resolution="1080p"):
    now = datetime.now(timezone.utc)
    duration = max(10, shots * 5)
    return CinematicProject(
        id="f" * 32,
        revision=7,
        title="OWNER PRIVATE FILM TITLE",
        master_prompt="SECRET MASTER SCRIPT FOR 3D MOVIE",
        target_duration_seconds=duration,
        delivery_fps=fps,
        delivery_resolution=resolution,
        aspect_ratio="16:9",
        continuity_bible={"freeform_notes": {"secret": "COSTUME_IDENTITY_SECRET"}},
        reference_image_ids=[REF] if refs is None else refs,
        scenes=[
            CinematicScene(
                scene_id="1" * 32,
                ordinal=1,
                title="SECRET SCENE",
                target_duration_seconds=duration,
                shots=[
                    CinematicShot(
                        shot_id=f"{100 + i:032x}",
                        ordinal=i + 1,
                        title="SECRET SHOT",
                        prompt="PRIVATE CHARACTER DESCRIPTION",
                        duration_seconds=5 if shots else 1,
                    )
                    for i in range(shots)
                ],
            )
        ],
        created_at=now,
        updated_at=now,
    )


def _png(workspace):
    directory = workspace / "video-assets"
    directory.mkdir()
    Image.new("RGB", (4, 4), (25, 18, 62)).save(directory / (REF + ".png"))


def _statuses(report):
    return [stage.status for stage in report.stages]


def test_no_optional_checks_do_not_falsely_pass(monkeypatch):
    import app.video.cinematic_preflight_dossier as module

    def must_not_call(*args, **kwargs):
        raise AssertionError("unchecked stage performed an operation")

    monkeypatch.setattr(module, "audit_engine_capabilities", must_not_call)
    monkeypatch.setattr(module, "audit_reference_files", must_not_call)

    report = audit_project_preflight(_project())
    assert report.preflight_complete is False
    assert report.preflight_passed is False
    assert report.completed_stages == 1
    assert report.total_stages == 3
    assert report.blockers == 0
    assert _statuses(report) == ["passed", "not_checked", "not_checked"]
    assert report.stages[1].detail is None
    assert report.stages[2].detail is None


def test_capabilities_only_is_incomplete_even_when_valid(monkeypatch):
    import app.video.cinematic_preflight_dossier as module

    def must_not_read_media(*args, **kwargs):
        raise AssertionError("unexpected local source read")

    monkeypatch.setattr(module, "audit_reference_files", must_not_read_media)
    report = audit_project_preflight(
        _project(), capabilities=FakeVideoEngine().capabilities()
    )
    assert _statuses(report) == ["passed", "passed", "not_checked"]
    assert report.completed_stages == 2
    assert not report.preflight_passed


def test_valid_all_three_produces_conservative_preflight_pass(tmp_path):
    _png(tmp_path)
    report = audit_project_preflight(
        _project(),
        capabilities=FakeVideoEngine().capabilities(),
        trusted_workspace=tmp_path,
    )
    assert report.preflight_complete
    assert report.preflight_passed
    assert report.blockers == 0
    assert report.shot_count == 2
    assert _statuses(report) == ["passed", "passed", "passed"]
    assert report.as_dict()["stages"][2]["detail"]["valid_unique_references"] == 1
    assert "ready_to_render" not in report.as_dict()
    assert "render_authorized" not in report.as_dict()


def test_missing_image_blocks_even_if_engine_and_timeline_pass(tmp_path):
    (tmp_path / "video-assets").mkdir()
    report = audit_project_preflight(
        _project(),
        capabilities=FakeVideoEngine().capabilities(),
        trusted_workspace=tmp_path,
    )
    assert _statuses(report) == ["passed", "passed", "blocked"]
    assert report.preflight_complete
    assert not report.preflight_passed
    assert report.blockers == 2


def test_unavailable_engine_blocks_even_when_image_is_good(tmp_path):
    _png(tmp_path)
    unavailable = FakeVideoEngine().capabilities().model_copy(
        update={"available": False}
    )
    report = audit_project_preflight(
        _project(), capabilities=unavailable, trusted_workspace=tmp_path
    )
    assert _statuses(report) == ["passed", "blocked", "passed"]
    assert not report.preflight_passed
    assert report.blockers == 1


def test_all_diagnostics_present_without_short_circuiting(tmp_path):
    (tmp_path / "video-assets").mkdir()
    project = _project(refs=[])
    project.scenes[0].target_duration_seconds = 11
    report = audit_project_preflight(
        project, capabilities=FakeVideoEngine().capabilities(), trusted_workspace=tmp_path
    )
    assert _statuses(report) == ["blocked", "passed", "blocked"]
    assert report.blockers >= 5
    assert report.stages[0].errors >= 3
    assert report.stages[2].errors == 2


def test_long_project_does_not_apply_arbitrary_shot_ceiling(tmp_path):
    _png(tmp_path)
    report = audit_project_preflight(
        _project(shots=640),
        capabilities=FakeVideoEngine().capabilities(),
        trusted_workspace=tmp_path,
    )
    assert report.shot_count == 640
    assert report.preflight_passed
    assert report.stages[2].detail["unique_references"] == 1
    assert report.stages[2].detail["shots_with_valid_references"] == 640


def test_native_generation_diff_is_a_warning_not_claim_of_4k(tmp_path):
    _png(tmp_path)
    report = audit_project_preflight(
        _project(fps=120, resolution="2160p"),
        capabilities=FakeVideoEngine().capabilities(),
        trusted_workspace=tmp_path,
    )
    assert report.preflight_passed
    assert report.stages[1].warnings == 2
    assert report.stages[1].detail["selected_native_fps"] == 60
    assert report.stages[1].detail["selected_native_resolution"] == "1080p"


def test_report_never_includes_private_assets_prompts_paths_or_engine_details(tmp_path):
    _png(tmp_path)
    project = _project()
    caps = FakeVideoEngine().capabilities().model_copy(
        update={"detail": "PRIVATE ENGINE DETAIL"}
    )
    before = project.model_dump(mode="json")
    first = audit_project_preflight(
        project, capabilities=caps, trusted_workspace=tmp_path
    )
    second = audit_project_preflight(
        project, capabilities=caps, trusted_workspace=tmp_path
    )
    serialized = json.dumps(first.as_dict())
    assert first == second
    assert project.model_dump(mode="json") == before
    for marker in (
        "OWNER PRIVATE", "SECRET", "PRIVATE CHARACTER", "COSTUME_IDENTITY",
        "PRIVATE ENGINE DETAIL", str(tmp_path), REF,
    ):
        assert marker not in serialized


def test_stage_counts_and_error_findings_match(tmp_path):
    (tmp_path / "video-assets").mkdir()
    project = _project(refs=[])
    unavailable = FakeVideoEngine().capabilities().model_copy(update={"available": False})
    report = audit_project_preflight(
        project, capabilities=unavailable, trusted_workspace=tmp_path,
    )
    assert report.blockers == sum(stage.errors for stage in report.stages)
    for stage in report.stages:
        assert stage.errors == sum(
            finding["severity"] == "error"
            for finding in stage.detail["findings"]
        )


def test_empty_timeline_fails_closed(tmp_path):
    _png(tmp_path)
    project = _project()
    project.scenes = []
    report = audit_project_preflight(
        project, capabilities=FakeVideoEngine().capabilities(), trusted_workspace=tmp_path,
    )
    assert report.shot_count == 0
    assert not report.preflight_passed
    assert _statuses(report) == ["blocked", "blocked", "blocked"]
