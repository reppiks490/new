from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from app.video.cinematic_models import CinematicProject, CinematicScene, CinematicShot
from app.video.cinematic_quality import audit_timeline

REF = "a" * 32


def _project(
    *,
    scene_lengths: tuple[tuple[float, ...], ...] = ((4.0, 6.0),),
    target: float = 10.0,
    references: bool = True,
    project_immutable=None,
    scene_immutable=None,
    shot_immutable=None,
) -> CinematicProject:
    scenes = []
    for scene_index, lengths in enumerate(scene_lengths, start=1):
        shots = []
        for shot_index, duration in enumerate(lengths, start=1):
            shots.append(
                CinematicShot(
                    shot_id=f"{scene_index * 100 + shot_index:032x}",
                    ordinal=shot_index,
                    title="Private shot",
                    prompt="Secret shot prompt must not appear in report",
                    duration_seconds=duration,
                    continuity_patch={"immutable_constraints": shot_immutable},
                )
            )
        scenes.append(
            CinematicScene(
                scene_id=f"{scene_index:032x}",
                ordinal=scene_index,
                title="Private scene",
                source_text="Private source content",
                target_duration_seconds=sum(lengths) if lengths else 1.0,
                shots=shots,
                continuity_patch={"immutable_constraints": scene_immutable},
            )
        )
    now = datetime.now(timezone.utc)
    return CinematicProject(
        id="f" * 32,
        revision=7,
        title="Secret project title",
        master_prompt="PRIVATE_MASTER_PROMPT",
        target_duration_seconds=target,
        delivery_fps=24,
        delivery_resolution="1080p",
        aspect_ratio="16:9",
        continuity_bible={
            "immutable_constraints": project_immutable,
            "freeform_notes": {"hidden": "never report me"},
        },
        reference_image_ids=[REF] if references else [],
        scenes=scenes,
        created_at=now,
        updated_at=now,
    )


def _codes(report):
    return [finding.code for finding in report.findings]


def test_valid_timeline_reports_metadata_readiness_without_claiming_engine_health():
    report = audit_timeline(_project(scene_lengths=((4.0, 1.0), (2.0, 3.0))))
    assert report.structurally_ready
    assert (report.scene_count, report.shot_count, report.source_reference_shots) == (2, 4, 4)
    assert report.planned_seconds == 10.0
    assert report.findings == ()


def test_missing_sources_and_duration_mismatches_are_scoped():
    project = _project(target=12, references=False)
    project.scenes[0].target_duration_seconds = 9
    report = audit_timeline(project)
    assert not report.structurally_ready
    assert _codes(report) == [
        "NO_SOURCE_REFERENCE", "NO_SOURCE_REFERENCE",
        "SCENE_DURATION_MISMATCH", "PROJECT_DURATION_MISMATCH",
    ]
    assert report.findings[0].shot_id == project.scenes[0].shots[0].shot_id


def test_reports_immutable_inheritance_conflicts_without_disclosing_values():
    project = _project(
        project_immutable={"character": "secret A"},
        scene_immutable={"character": "secret B"},
        shot_immutable={"character": "secret C"},
    )
    report = audit_timeline(project)
    assert _codes(report).count("IMMUTABLE_CONTINUITY_OVERRIDE") == 3
    text = json.dumps(report.as_dict())
    for private in ("secret A", "secret B", "secret C", "Secret shot", "PRIVATE_MASTER_PROMPT"):
        assert private not in text


def test_order_warnings_are_nonblocking_and_input_is_unchanged():
    project = _project()
    scene = project.scenes[0]
    scene.ordinal = 9
    scene.shots[0].ordinal = 2
    scene.shots[1].ordinal = 1
    before = project.model_dump(mode="json")
    first = audit_timeline(project)
    second = audit_timeline(project)
    assert first.structurally_ready
    assert _codes(first) == ["SCENE_ORDER_MISMATCH", "SHOT_ORDER_MISMATCH"]
    assert first == second
    assert project.model_dump(mode="json") == before


def test_decimal_budget_avoids_binary_float_noise():
    report = audit_timeline(
        _project(scene_lengths=((0.1, 0.2, 9.7),), target=10.0),
        tolerance_seconds=0,
    )
    assert "PROJECT_DURATION_MISMATCH" not in _codes(report)
    assert "SCENE_DURATION_MISMATCH" not in _codes(report)


def test_empty_scene_and_empty_project_are_not_ready():
    project = _project(scene_lengths=((),))
    assert "EMPTY_SCENE" in _codes(audit_timeline(project))
    empty = project.model_copy(update={"scenes": []})
    assert "NO_SCENES" in _codes(audit_timeline(empty))


@pytest.mark.parametrize("bad", [-0.1, float("nan"), float("inf")])
def test_invalid_tolerances_are_rejected(bad):
    with pytest.raises(ValueError, match="finite"):
        audit_timeline(_project(), tolerance_seconds=bad)


def test_duplicate_scene_id_after_mutation_blocks_structural_readiness():
    project = _project(scene_lengths=((5.0, 5.0), (5.0, 5.0)), target=20)
    second_scene = project.scenes[1]
    second_scene.scene_id = project.scenes[0].scene_id
    before = project.model_dump(mode="json")
    report = audit_timeline(project)
    assert not report.structurally_ready
    assert _codes(report) == ["DUPLICATE_SCENE_ID"]
    assert report.findings[0].scene_id == second_scene.scene_id
    assert project.model_dump(mode="json") == before


def test_duplicate_shot_id_across_scenes_blocks_preflight():
    project = _project(scene_lengths=((5.0, 5.0), (5.0, 5.0)), target=20)
    duplicate = project.scenes[1].shots[0]
    duplicate.shot_id = project.scenes[0].shots[0].shot_id
    report = audit_timeline(project)
    assert not report.structurally_ready
    assert _codes(report) == ["DUPLICATE_SHOT_ID"]
    assert report.findings[0].shot_id == duplicate.shot_id
    assert report.findings[0].scene_id == project.scenes[1].scene_id


def test_duplicate_shot_id_within_scene_is_not_silently_accepted():
    project = _project()
    first, second = project.scenes[0].shots
    second.shot_id = first.shot_id
    report = audit_timeline(project)
    assert not report.structurally_ready
    assert _codes(report) == ["DUPLICATE_SHOT_ID"]
    assert "Secret shot" not in json.dumps(report.as_dict())
