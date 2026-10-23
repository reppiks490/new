"""Hermetic render-input revision audit tests; never execute any render job."""
from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from app.video.cinematic_models import (
    CinematicProject, CinematicScene, CinematicShot, ContinuityPatch, ContinuityState
)
from app.video.cinematic_revision_impact import (
    RevisionImpactError, analyze_cinematic_revision
)


def _project(*, shot_count: int = 3, fps: int = 24) -> CinematicProject:
    now = datetime(2026, 10, 22, tzinfo=timezone.utc)
    shots = [
        CinematicShot(
            shot_id=f'{100 + i:032x}', ordinal=i + 1,
            title=f'Shot {i + 1}', prompt=f'PRIVATE_PROMPT_{i}',
            duration_seconds=5, seed=42, engine_profile='balanced',
        )
        for i in range(shot_count)
    ]
    seconds = max(10, 5 * shot_count)
    return CinematicProject(
        id='f' * 32, revision=10, title='PRIVATE_TITLE',
        master_prompt='PRIVATE_MASTER_STORY',
        target_duration_seconds=seconds,
        delivery_fps=fps, delivery_resolution='2160p', aspect_ratio='16:9',
        continuity_bible=ContinuityState(
            weather='PRIVATE_SUNSHINE', wardrobe={'style': 'PRIVATE_COAT'}
        ),
        reference_image_ids=['a' * 32],
        scenes=[CinematicScene(
            scene_id='b' * 32, ordinal=1, title='PRIVATE_SCENE',
            source_text='PRIVATE_SOURCE_TEXT', target_duration_seconds=seconds,
            shots=shots,
        )],
        created_at=now, updated_at=now,
    )


def _replace_shot(project, position, **updates):
    scene = project.scenes[0]
    shots = list(scene.shots)
    shots[position] = shots[position].model_copy(update=updates)
    replacement = scene.model_copy(update={'shots': shots})
    return project.model_copy(update={'revision': project.revision + 1, 'scenes': [replacement]})


def _impact(project, **updates):
    return analyze_cinematic_revision(
        project, project.model_copy(update={'revision': project.revision + 1, **updates})
    )


def test_metadata_only_revision_never_claims_new_video_work():
    original = _project()
    report = _impact(original, title='A changed private project title')
    assert report.project_id == original.id
    assert report.shots_requiring_render == 0
    assert report.reused_unchanged_shots == 3
    assert report.changed_shots == 0
    assert not report.requires_master_reassembly
    assert not report.requires_recompile
    assert not report.requires_creative_review
    assert report.reason_codes == ()
    assert all(x.state == 'unchanged' for x in report.shots)


@pytest.mark.parametrize('field,new_value,expected_reason', [
    ('prompt', 'PRIVATE_NEW_ACTION', 'SHOT_PROMPT_CHANGED'),
    ('negative_prompt', 'PRIVATE_NEGATIVE', 'SHOT_NEGATIVE_PROMPT_CHANGED'),
    ('duration_seconds', 4, 'SHOT_DURATION_CHANGED'),
    ('seed', 100, 'SHOT_SEED_CHANGED'),
    ('engine_profile', 'high_quality', 'SHOT_ENGINE_PROFILE_CHANGED'),
    ('camera_motion', 'orbit', 'SHOT_CAMERA_MOTION_CHANGED'),
    ('motion_strength', 0.8, 'SHOT_MOTION_STRENGTH_CHANGED'),
])
def test_actual_engine_input_changes_invalidate_only_affected_shot(field, new_value, expected_reason):
    original = _project()
    revised = _replace_shot(original, 1, **{field: new_value})
    report = analyze_cinematic_revision(original, revised)
    assert report.shots_requiring_render == 1
    assert report.changed_shots == 1
    assert report.reused_unchanged_shots == 2
    assert report.requires_master_reassembly
    assert expected_reason in report.shots[1].reason_codes
    assert not report.shots[0].requires_new_render
    assert not report.shots[2].requires_new_render


def test_inherited_continuity_only_invalidates_nonoverridden_shots():
    original = _project()
    patch = ContinuityPatch(weather='PRIVATE_STORM')
    overridden = _replace_shot(original, 1, continuity_patch=patch)
    second_scene = overridden.scenes[0]
    old = original.model_copy(update={
        'scenes': [original.scenes[0].model_copy(update={
            'shots': [original.scenes[0].shots[0], overridden.scenes[0].shots[1], original.scenes[0].shots[2]]
        })]
    })
    assert second_scene is not None
    new_bible = old.continuity_bible.model_copy(update={'weather': 'PRIVATE_RAIN'})
    revised = old.model_copy(update={
        'revision': old.revision + 1, 'continuity_bible': new_bible
    })
    report = analyze_cinematic_revision(old, revised)
    assert report.shots_requiring_render == 2
    assert [s.requires_new_render for s in report.shots] == [True, False, True]
    assert report.reused_unchanged_shots == 1
    assert not report.requires_creative_review


def test_reference_changes_invalidate_only_effectively_affected_shot():
    original = _project()
    revised = _replace_shot(
        original, 2, reference_image_ids=['c' * 32]
    )
    report = analyze_cinematic_revision(original, revised)
    assert report.shots_requiring_render == 1
    assert report.shots[2].reason_codes == ('EFFECTIVE_REFERENCE_SET_CHANGED',)
    assert 'c' * 32 not in json.dumps(report.to_dict())


def test_reorder_requires_reassembly_not_regeneration():
    original = _project()
    old_scene = original.scenes[0]
    reordered = old_scene.model_copy(update={'shots': list(reversed(old_scene.shots))})
    revised = original.model_copy(update={
        'revision': 11, 'scenes': [reordered]
    })
    report = analyze_cinematic_revision(original, revised)
    assert report.shots_requiring_render == 0
    assert report.requires_master_reassembly
    assert not report.requires_recompile
    assert 'SHOT_SEQUENCE_CHANGED' in report.reason_codes
    assert [s.shot_id for s in report.shots] == [s.shot_id for s in reordered.shots]
    assert all(not s.requires_new_render for s in report.shots)


def test_added_and_removed_shots_are_reported_without_rendering_removed_sources():
    original = _project()
    shots = original.scenes[0].shots
    new_shot = CinematicShot(
        shot_id='d' * 32, ordinal=3, title='Private replacement',
        prompt='PRIVATE_NEW', duration_seconds=5
    )
    after = original.model_copy(update={
        'revision': 11,
        'scenes': [original.scenes[0].model_copy(update={
            'shots': [shots[0], shots[1], new_shot],
        })],
    })
    report = analyze_cinematic_revision(original, after)
    assert report.added_shots == 1
    assert report.removed_shots == 1
    assert report.shots_requiring_render == 1
    assert report.requires_master_reassembly
    assert report.shots[-1].state == 'removed'
    assert report.shots[-1].requires_new_render is False


def test_delivery_fps_and_resolution_conservatively_invalidate_all_shots():
    original = _project()
    updated = _impact(original, delivery_fps=120, delivery_resolution='1080p')
    assert updated.shots_requiring_render == 3
    assert updated.requires_master_reassembly
    assert all(s.requires_new_render for s in updated.shots)
    assert not updated.requires_recompile
    assert 'PROJECT_DELIVERY_FPS_CHANGED' in updated.reason_codes
    assert 'PROJECT_DELIVERY_RESOLUTION_CHANGED' in updated.reason_codes


def test_aspect_ratio_and_delivery_target_affect_finishing_not_input_shots():
    original = _project()
    changed = _impact(original, aspect_ratio='4:3', target_duration_seconds=30)
    assert changed.shots_requiring_render == 0
    assert changed.requires_master_reassembly
    assert changed.requires_recompile
    assert changed.reused_unchanged_shots == 3


def test_unforwarded_creative_controls_require_explicit_review():
    original = _project()
    revised = _replace_shot(
        original, 0, lens_mm=35.0, framing='PRIVATE_FRAMING',
        transition_in='PRIVATE_CROSS_FADE'
    )
    report = analyze_cinematic_revision(original, revised)
    assert report.shots_requiring_render == 0
    assert report.requires_creative_review
    assert report.shots[0].requires_creative_review
    assert report.requires_master_reassembly
    assert 'UNFORWARDED_CREATIVE_CAMERA_CONTROLS_CHANGED' in report.shots[0].reason_codes
    assert 'UNIMPLEMENTED_TRANSITION_INTENT_CHANGED' in report.shots[0].reason_codes
    assert 'PRIVATE_FRAMING' not in json.dumps(report.to_dict())


def test_screenplay_source_change_marks_recompile_without_fabricating_new_render():
    original = _project()
    updated = _impact(original, master_prompt='PRIVATE_REVISED_STORY')
    assert updated.requires_recompile
    assert updated.requires_master_reassembly
    assert updated.shots_requiring_render == 0
    assert 'MASTER_SCREENPLAY_CHANGED' in updated.reason_codes


def test_new_scene_relationship_invalidates_scene_specific_job_linkage():
    original = _project()
    first, middle, third = original.scenes[0].shots
    scene_1 = original.scenes[0].model_copy(update={
        'shots': [first, third]
    })
    scene_2 = CinematicScene(
        scene_id='c' * 32, ordinal=2, title='PRIVATE_B',
        target_duration_seconds=5, shots=[middle],
    )
    revised = original.model_copy(update={'revision': 11, 'scenes': [scene_1, scene_2]})
    report = analyze_cinematic_revision(original, revised)
    target = next(x for x in report.shots if x.shot_id == middle.shot_id)
    assert target.requires_new_render
    assert 'SHOT_MOVED_TO_DIFFERENT_SCENE' in target.reason_codes
    assert report.shots_requiring_render == 1
    assert report.requires_recompile
    assert report.requires_master_reassembly


def test_job_link_changes_are_not_mistaken_for_prompt_changes():
    original = _project()
    updated = _replace_shot(original, 0, latest_job_id='e' * 32,
                            latest_rendered_project_revision=11)
    report = analyze_cinematic_revision(original, updated)
    assert report.shots_requiring_render == 0
    assert report.reused_unchanged_shots == 3


def test_does_not_leak_creative_values_or_image_reference_ids():
    original = _project()
    revised = _replace_shot(
        original, 0, prompt='PRIVATE_NEW_ACTION',
        reference_image_ids=['c' * 32],
    )
    report = analyze_cinematic_revision(original, revised)
    payload = json.dumps(report.to_dict())
    for secret in (
        'PRIVATE_', 'SUNSHINE', 'COAT', 'PRIVATE_NEW_ACTION',
        'c' * 32, 'a' * 32,
    ):
        assert secret not in payload
    assert len(report.shots) == 3


@pytest.mark.parametrize('mismatch', [
    {'id': 'a' * 32},
    {'revision': 10},
    {'revision': 9},
])
def test_foreign_or_nonforward_revision_rejected(mismatch):
    old = _project()
    newer = old.model_copy(update={'revision': 11, **mismatch})
    with pytest.raises(RevisionImpactError):
        analyze_cinematic_revision(old, newer)


def test_duplicate_ids_rejected_even_when_pydantic_validation_was_bypassed():
    original = _project()
    shots = original.scenes[0].shots
    extra = original.scenes[0].model_copy(update={'shots': [shots[0], shots[0]]})
    altered = original.model_copy(update={'revision': 11, 'scenes': [extra]})
    with pytest.raises(RevisionImpactError, match='duplicate shot IDs'):
        analyze_cinematic_revision(original, altered)


def test_large_unbounded_640_shot_revision_remains_precise():
    original = _project(shot_count=640)
    revised = _replace_shot(original, 639, prompt='PRIVATE_LAST_SHOT_CHANGED')
    report = analyze_cinematic_revision(original, revised)
    assert len(report.shots) == 640
    assert report.shots_requiring_render == 1
    assert report.reused_unchanged_shots == 639
    assert report.shots[-1].requires_new_render
    assert report.changed_shots == 1
