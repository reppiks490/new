"""Director's cut: frame-level, hermetic, privacy-safe non-destructive tests."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json

import pytest

from app.video.cinematic_directors_cut import (
    CutSelection,
    plan_directors_cut,
    verify_directors_cut,
)
from app.video.cinematic_editing import TimelineValidationError, preflight_editorial_timeline
from app.video.cinematic_models import (
    CinematicProject, CinematicScene, CinematicShot, ContinuityPatch, ContinuityState
)


def _project(*, fps: int = 24) -> CinematicProject:
    now = datetime(2026, 10, 22, tzinfo=timezone.utc)
    shots = [
        CinematicShot(
            shot_id=f'{idx + 100:032x}', ordinal=idx + 1, title=f'Shot {idx + 1}',
            prompt=f'SECRET_SCREENPLAY_{idx}', duration_seconds=duration,
            continuity_patch=patch,
            transition_in='SECRET_DISSOLVE' if idx == 0 else None,
            transition_out='SECRET_CUT' if idx == 2 else None,
        )
        for idx, (duration, patch) in enumerate([
            (4, ContinuityPatch()),
            (3, ContinuityPatch(wardrobe={'private': 'RED_COAT_SECRET'})),
            (3, ContinuityPatch(weather='PRIVATE_STORM')),
        ])
    ]
    return CinematicProject(
        id='a' * 32, revision=4, title='PRIVATE_TITLE',
        master_prompt='PRIVATE_SCREENPLAY',
        target_duration_seconds=10,
        delivery_fps=fps, delivery_resolution='2160p',
        aspect_ratio='16:9', created_at=now, updated_at=now,
        continuity_bible=ContinuityState(
            wardrobe={'private': 'GREEN_COAT_SECRET'},
            weather='PRIVATE_SUNSHINE',
        ),
        scenes=[
            CinematicScene(
                scene_id='b' * 32, ordinal=1, title='PRIVATE_SCENE',
                target_duration_seconds=10, shots=shots,
            )
        ],
    )


def test_identity_cut_is_exact_and_original_project_is_unchanged():
    project = _project()
    before = deepcopy(project)
    identifiers = [shot.shot_id for shot in project.scenes[0].shots]
    cut = plan_directors_cut(project, [CutSelection(s) for s in identifiers])
    assert project == before
    assert cut.project_revision == 4
    assert cut.fps == 24
    assert cut.frame_count == 240
    assert [s.frame_count for s in cut.segments] == [96, 72, 72]
    assert [(s.edit_in_frame, s.edit_out_frame_exclusive) for s in cut.segments] == [
        (0, 96), (96, 168), (168, 240),
    ]
    assert cut.source_timeline_digest_sha256 == preflight_editorial_timeline(
        project
    ).timeline_digest_sha256
    assert cut.segment_at_frame(0) == cut.segments[0]
    assert cut.segment_at_frame(96) == cut.segments[1]
    assert cut.segment_at_frame(239) == cut.segments[2]


def test_trim_and_repeat_are_half_open_and_contiguous():
    project = _project()
    shot_id = project.scenes[0].shots[0].shot_id
    cut = plan_directors_cut(project, [
        CutSelection(shot_id, 1, 8),
        CutSelection(shot_id, 4, 10),
        CutSelection(shot_id, source_in_frame=95),
    ])
    assert cut.frame_count == 14
    assert [s.frame_count for s in cut.segments] == [7, 6, 1]
    assert [s.edit_out_frame_exclusive for s in cut.segments] == [7, 13, 14]
    assert [cut.segment_at_frame(n) for n in (0, 6, 7, 12, 13)] == [
        cut.segments[0], cut.segments[0], cut.segments[1],
        cut.segments[1], cut.segments[2],
    ]
    assert all(not s.transition_in_declared for s in cut.segments)


def test_reordered_shots_recalculate_continuity_without_leaking_values():
    project = _project()
    original = project.scenes[0].shots
    cut = plan_directors_cut(project, [
        CutSelection(original[2].shot_id),
        CutSelection(original[0].shot_id),
        CutSelection(original[1].shot_id),
    ])
    assert [s.shot_id for s in cut.segments] == [
        original[2].shot_id, original[0].shot_id, original[1].shot_id,
    ]
    assert cut.segments[0].continuity_changed_fields == ()
    assert cut.segments[1].continuity_changed_fields == ('weather',)
    assert cut.segments[2].continuity_changed_fields == ('wardrobe',)
    assert cut.segments[1].transition_in_declared is True
    assert cut.segments[0].transition_out_declared is True
    payload = json.dumps(cut.to_dict())
    for private in ('PRIVATE_', 'SECRET_', 'GREEN_COAT', 'RED_COAT'):
        assert private not in payload


def test_stale_or_mismatched_precomputed_timeline_is_rejected():
    project = _project()
    timeline = preflight_editorial_timeline(project)
    one = project.scenes[0].shots[0].shot_id
    assert plan_directors_cut(project, [CutSelection(one)], source_timeline=timeline)
    revised = project.model_copy(update={'revision': 5})
    with pytest.raises(TimelineValidationError, match='does not match'):
        plan_directors_cut(revised, [CutSelection(one)], source_timeline=timeline)


@pytest.mark.parametrize('start,end', [
    (-1, 5), (0, 0), (20, 19), (0, 97), (1.0, 2),
    (True, 2), (0, False), (0, '6')
])
def test_invalid_source_bounds_fail_without_mutating_project(start, end):
    project = _project()
    old = deepcopy(project)
    shot = project.scenes[0].shots[0]
    with pytest.raises(TimelineValidationError, match='bounds'):
        plan_directors_cut(project, [
            CutSelection(shot.shot_id, source_in_frame=start, source_out_frame_exclusive=end)
        ])
    assert project == old


def test_unknown_shot_and_empty_cut_are_rejected():
    project = _project()
    with pytest.raises(TimelineValidationError, match='at least one'):
        plan_directors_cut(project, [])
    with pytest.raises(TimelineValidationError, match='unknown shot'):
        plan_directors_cut(project, [CutSelection('f' * 32)])
    with pytest.raises(TimelineValidationError, match='CutSelection'):
        plan_directors_cut(project, [project.scenes[0].shots[0].shot_id])


def test_fractional_and_long_timeline_use_integer_frame_offsets():
    project = _project(fps=120)
    cut = plan_directors_cut(project, [
        CutSelection(project.scenes[0].shots[0].shot_id, source_in_frame=1),
        CutSelection(project.scenes[0].shots[2].shot_id, source_out_frame_exclusive=150),
    ])
    assert cut.frame_count == 479 + 150
    assert cut.segments[0].edit_out_frame_exclusive == 479
    assert cut.segments[1].edit_out_frame_exclusive == 629
    assert cut.segment_at_frame(628) == cut.segments[1]


def test_cut_fingerprint_changes_with_order_trims_and_revision():
    project = _project()
    a, b = (s.shot_id for s in project.scenes[0].shots[:2])
    selections = [CutSelection(a), CutSelection(b)]
    initial = plan_directors_cut(project, selections)
    assert initial.cut_digest_sha256 == plan_directors_cut(project, selections).cut_digest_sha256
    assert initial.cut_digest_sha256 != plan_directors_cut(
        project, [CutSelection(b), CutSelection(a)]
    ).cut_digest_sha256
    assert initial.cut_digest_sha256 != plan_directors_cut(
        project, [CutSelection(a, 0, 95), CutSelection(b)]
    ).cut_digest_sha256
    assert initial.cut_digest_sha256 != plan_directors_cut(
        project.model_copy(update={'revision': 5}), selections
    ).cut_digest_sha256


def test_out_of_range_frame_lookup_is_strict():
    project = _project()
    cut = plan_directors_cut(project, [CutSelection(project.scenes[0].shots[0].shot_id)])
    for value in (-1, cut.frame_count, 2.1, True):
        with pytest.raises(IndexError):
            cut.segment_at_frame(value)


def test_cross_scene_resequencing_marks_scene_switch_without_exposing_titles():
    project = _project()
    scene_a = project.scenes[0]
    scene_b = CinematicScene(
        scene_id='c' * 32, ordinal=2, title='PRIVATE_OTHER_SCENE',
        target_duration_seconds=10,
        shots=[CinematicShot(
            shot_id='d' * 32, ordinal=1, title='PRIVATE_SHOT',
            prompt='PRIVATE_ACTION', duration_seconds=10,
            continuity_patch=ContinuityPatch(weather='PRIVATE_RAIN'),
        )],
    )
    extended = project.model_copy(update={
        'scenes': [scene_a, scene_b],
        'target_duration_seconds': 20,
    })
    cut = plan_directors_cut(extended, [
        CutSelection(scene_a.shots[0].shot_id),
        CutSelection(scene_b.shots[0].shot_id),
        CutSelection(scene_a.shots[1].shot_id),
    ])
    assert [s.scene_changed for s in cut.segments] == [False, True, True]
    assert cut.segments[1].continuity_changed_fields == ('weather',)
    assert cut.segments[2].continuity_changed_fields == ('wardrobe', 'weather')
    assert 'PRIVATE' not in json.dumps(cut.to_dict())


def test_input_metadata_counts_never_imply_footage_exists():
    project = _project()
    shot = project.scenes[0].shots[0]
    cut = plan_directors_cut(project, [CutSelection(shot.shot_id)])
    fields = cut.to_dict()
    assert 'asset_url' not in json.dumps(fields)
    assert 'rendered' not in json.dumps(fields)
    assert 'source_timeline_digest_sha256' in fields
    assert len(fields['cut_digest_sha256']) == 64


def test_saved_cut_snapshot_verification_detects_stale_or_tampered_metadata():
    project = _project()
    shot = project.scenes[0].shots[0]
    cut = plan_directors_cut(project, [CutSelection(shot.shot_id, 0, 23)])
    assert cut.schema_version == 1
    assert verify_directors_cut(project, cut) is None

    for forged in [
        replace(cut, schema_version=2),
        replace(cut, frame_count=cut.frame_count + 1),
        replace(cut, cut_digest_sha256='0' * 64),
        replace(cut, segments=(replace(
            cut.segments[0], source_out_frame_exclusive=24
        ),)),
        replace(cut, segments=(replace(
            cut.segments[0], continuity_changed_fields=('private-note',)
        ),)),
    ]:
        with pytest.raises(TimelineValidationError):
            verify_directors_cut(project, forged)

    revised = project.model_copy(update={'revision': project.revision + 1})
    with pytest.raises(TimelineValidationError, match='does not match'):
        verify_directors_cut(revised, cut)
    assert project.revision == 4


def test_directors_cut_verifier_rejects_empty_snapshot_without_partial_success():
    project = _project()
    cut = plan_directors_cut(
        project, [CutSelection(project.scenes[0].shots[0].shot_id)]
    )
    with pytest.raises(TimelineValidationError, match='no segments'):
        verify_directors_cut(project, replace(cut, segments=()))
