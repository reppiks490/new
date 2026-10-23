"""Safe archive migration is a read-only preview, never a footage reuse gate."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json

import pytest

from app.video.cinematic_cut_migration import preview_directors_cut_migration
from app.video.cinematic_directors_cut import CutSelection, plan_directors_cut
from app.video.cinematic_editing import TimelineValidationError
from app.video.cinematic_models import (
    CinematicProject, CinematicScene, CinematicShot, ContinuityState,
)
from app.video.cinematic_revision_impact import RevisionImpactError


def _project(count: int = 3, fps: int = 24) -> CinematicProject:
    now = datetime(2026, 10, 22, tzinfo=timezone.utc)
    shots = [
        CinematicShot(
            shot_id=f'{100 + i:032x}', ordinal=i + 1,
            title=f'Private shot {i}', prompt=f'PRIVATE_SCRIPT_{i}',
            duration_seconds=5, seed=9,
        )
        for i in range(count)
    ]
    seconds = max(10, count * 5)
    return CinematicProject(
        id='a' * 32, revision=5, title='PRIVATE_PROJECT',
        master_prompt='PRIVATE_SCREENPLAY',
        target_duration_seconds=seconds, delivery_fps=fps,
        delivery_resolution='1080p', aspect_ratio='16:9',
        created_at=now, updated_at=now,
        continuity_bible=ContinuityState(weather='PRIVATE_SUN'),
        scenes=[CinematicScene(
            scene_id='b' * 32, ordinal=1, title='Private scene',
            target_duration_seconds=seconds, shots=shots,
        )],
    )


def _change_shot(project: CinematicProject, idx: int, **kwargs) -> CinematicProject:
    scene = project.scenes[0]
    shots = list(scene.shots)
    shots[idx] = shots[idx].model_copy(update=kwargs)
    return project.model_copy(update={
        'revision': project.revision + 1,
        'scenes': [scene.model_copy(update={'shots': shots})],
    })


def _cut(project: CinematicProject):
    shots = project.scenes[0].shots
    return plan_directors_cut(project, [
        CutSelection(shots[1].shot_id, 2, 50),
        CutSelection(shots[0].shot_id, 0, 12),
        CutSelection(shots[1].shot_id, 10, 20),
    ])


def test_title_only_revision_portably_rebases_exact_frames_without_mutation():
    old = _project()
    new = old.model_copy(update={'revision': 6, 'title': 'NEW_PRIVATE_TITLE'})
    old_copy, new_copy = deepcopy(old), deepcopy(new)
    cut = _cut(old)
    preview = preview_directors_cut_migration(old, new, cut)
    assert preview.status == 'portable'
    assert preview.portable_segments == 3
    assert preview.review_segments == preview.blocked_segments == 0
    assert preview.proposed_cut is not None
    assert preview.proposed_cut.project_revision == 6
    assert preview.proposed_cut.frame_count == cut.frame_count == 70
    assert [s.shot_id for s in preview.proposed_cut.segments] == [
        s.shot_id for s in cut.segments
    ]
    assert preview.proposed_cut.cut_digest_sha256 != cut.cut_digest_sha256
    assert old == old_copy and new == new_copy


def test_explicit_reordering_preserves_saved_cut_order_without_rerendering():
    old = _project()
    scene = old.scenes[0]
    new = old.model_copy(update={
        'revision': 6,
        'scenes': [scene.model_copy(update={'shots': list(reversed(scene.shots))})],
    })
    preview = preview_directors_cut_migration(old, new, _cut(old))
    assert preview.status == 'portable'
    assert preview.proposed_cut is not None
    assert [s.shot_id for s in preview.proposed_cut.segments] == [
        scene.shots[1].shot_id, scene.shots[0].shot_id, scene.shots[1].shot_id,
    ]


def test_changed_prompt_marks_only_selected_shot_segments_for_review():
    old = _project()
    new = _change_shot(old, 1, prompt='PRIVATE_REVISED_SCRIPT')
    preview = preview_directors_cut_migration(old, new, _cut(old))
    assert preview.status == 'review_required'
    assert preview.review_segments == 2
    assert preview.portable_segments == 1
    assert preview.blocked_segments == 0
    assert [item.status for item in preview.segments] == [
        'review_required', 'portable', 'review_required'
    ]
    assert preview.segments[0].reason_codes == ('SOURCE_RENDER_INPUT_CHANGED',)
    assert preview.proposed_cut is not None  # plan only; never media approval


def test_scene_continuity_change_requires_review_for_selected_segments():
    old = _project()
    new = old.model_copy(update={
        'revision': 6,
        'continuity_bible': old.continuity_bible.model_copy(
            update={'weather': 'PRIVATE_NIGHT'}
        ),
    })
    preview = preview_directors_cut_migration(old, new, _cut(old))
    assert preview.status == 'review_required'
    assert preview.review_segments == 3
    assert all('SOURCE_RENDER_INPUT_CHANGED' in item.reason_codes for item in preview.segments)


def test_deleted_selected_shot_fails_closed_and_preserves_all_diagnostics():
    old = _project()
    scene = old.scenes[0]
    new = old.model_copy(update={
        'revision': 6,
        'scenes': [scene.model_copy(update={
            'shots': [scene.shots[0], scene.shots[2]]
        })],
    })
    preview = preview_directors_cut_migration(old, new, _cut(old))
    assert preview.status == 'blocked'
    assert preview.blocked_segments == 2
    assert preview.portable_segments == 1
    assert preview.proposed_cut is None
    assert [x.reason_codes for x in preview.segments] == [
        ('SOURCE_SHOT_REMOVED',), (), ('SOURCE_SHOT_REMOVED',)
    ]


def test_reduced_shot_duration_does_not_clamp_or_silently_drop_frames():
    old = _project()
    new = _change_shot(old, 1, duration_seconds=0.25)
    preview = preview_directors_cut_migration(old, new, _cut(old))
    assert preview.status == 'blocked'
    assert preview.blocked_segments == 2
    assert preview.proposed_cut is None
    assert preview.segments[0].reason_codes == ('TRIM_EXCEEDS_NEW_SOURCE',)


def test_changed_frame_rate_blocks_unsafe_offset_reinterpretation():
    old = _project()
    new = old.model_copy(update={'revision': 6, 'delivery_fps': 120})
    preview = preview_directors_cut_migration(old, new, _cut(old))
    assert preview.status == 'blocked'
    assert preview.blocked_segments == 3
    assert all(item.reason_codes == ('FRAME_RATE_CHANGED',) for item in preview.segments)
    assert preview.proposed_cut is None


def test_target_duration_and_screenplay_changes_require_explicit_compilation_review():
    old = _project()
    new = old.model_copy(update={
        'revision': 6, 'target_duration_seconds': 60,
        'master_prompt': 'PRIVATE_NEW_STORY',
    })
    preview = preview_directors_cut_migration(old, new, _cut(old))
    assert preview.status == 'review_required'
    assert preview.review_segments == 3
    assert all(item.reason_codes == ('COMPILATION_REVIEW_REQUIRED',)
               for item in preview.segments)
    assert preview.proposed_cut is not None


def test_aspect_change_requires_finishing_review_not_frame_rate_conversion():
    old = _project()
    new = old.model_copy(update={'revision': 6, 'aspect_ratio': '4:3'})
    preview = preview_directors_cut_migration(old, new, _cut(old))
    assert preview.status == 'review_required'
    assert all(item.reason_codes == ('FINISHING_ASPECT_RATIO_CHANGED',)
               for item in preview.segments)


def test_creative_lens_change_requests_review_without_inventing_engine_support():
    old = _project()
    new = _change_shot(old, 0, lens_mm=85.0)
    preview = preview_directors_cut_migration(old, new, _cut(old))
    assert preview.status == 'review_required'
    assert preview.segments[1].reason_codes == ('SOURCE_CREATIVE_INTENT_CHANGED',)
    assert preview.segments[0].status == 'portable'


def test_immutable_old_archive_must_match_original_project_revision():
    old = _project()
    cut = _cut(old)
    new = old.model_copy(update={'revision': 6})
    forged = replace(cut, project_revision=4)
    with pytest.raises(TimelineValidationError):
        preview_directors_cut_migration(old, new, forged)
    with pytest.raises(TimelineValidationError):
        preview_directors_cut_migration(old, new, replace(cut, frame_count=9999))
    with pytest.raises(TimelineValidationError):
        preview_directors_cut_migration(old.model_copy(update={'revision': 4}), new, cut)


def test_cross_project_and_backward_revision_cannot_rebase():
    old = _project()
    cut = _cut(old)
    foreign = old.model_copy(update={'id': 'f' * 32, 'revision': 6})
    with pytest.raises(RevisionImpactError):
        preview_directors_cut_migration(old, foreign, cut)
    with pytest.raises(RevisionImpactError):
        preview_directors_cut_migration(old, old, cut)


def test_report_never_exposes_private_creative_data_or_reference_ids():
    old = _project()
    new = _change_shot(old, 1, prompt='PRIVATE_CONFIDENTIAL_DIALOGUE')
    cut = _cut(old)
    report = preview_directors_cut_migration(old, new, cut)
    body = json.dumps(report.to_dict())
    assert 'PRIVATE' not in body
    assert 'SCREENPLAY' not in body
    assert 'reference_image_ids' not in body
    assert 'latest_asset_url' not in body
    assert 'rendered' not in body
    assert 'project_id' in body


def test_640_shot_cut_migration_does_not_sample_or_truncate():
    old = _project(count=640)
    shot_ids = [shot.shot_id for shot in old.scenes[0].shots]
    selections = [CutSelection(shot_id, 0, 12) for shot_id in shot_ids]
    old_cut = plan_directors_cut(old, selections)
    updated = _change_shot(old, 639, prompt='PRIVATE_CHANGED_LAST_SHOT')
    report = preview_directors_cut_migration(old, updated, old_cut)
    assert report.status == 'review_required'
    assert len(report.segments) == 640
    assert report.portable_segments == 639
    assert report.review_segments == 1
    assert report.blocked_segments == 0
    assert report.segments[-1].status == 'review_required'
    assert report.proposed_cut is not None
    assert report.proposed_cut.frame_count == old_cut.frame_count == 7680
