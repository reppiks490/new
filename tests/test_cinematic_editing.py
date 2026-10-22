"""Hermetic editorial preflight tests: no media codecs, GPU or network."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.video.cinematic_editing import (
    TimelineValidationError,
    preflight_editorial_timeline,
)
from app.video.cinematic_models import (
    CinematicProject,
    CinematicScene,
    CinematicShot,
    ContinuityPatch,
    ContinuityState,
)


def _shot(number: int, *, seconds: float = 10, **kwargs) -> CinematicShot:
    return CinematicShot(
        shot_id=f'{100 + number:032x}',
        ordinal=number,
        title=f'Shot {number}',
        prompt='A silent cinematic action.',
        duration_seconds=seconds,
        **kwargs,
    )


def _project(
    shots: list[CinematicShot],
    *,
    fps: int = 24,
    target_seconds: float = 600,
    scene_patch: ContinuityPatch | None = None,
    bible: ContinuityState | None = None,
) -> CinematicProject:
    now = datetime(2026, 10, 22, tzinfo=timezone.utc)
    return CinematicProject(
        id='a' * 32,
        revision=8,
        title='Feature-length shot plan',
        master_prompt='A cinematic sequence.',
        target_duration_seconds=target_seconds,
        delivery_fps=fps,
        delivery_resolution='2160p',
        aspect_ratio='16:9',
        continuity_bible=bible or ContinuityState(),
        scenes=[
            CinematicScene(
                scene_id='b' * 32,
                ordinal=1,
                title='Act one',
                target_duration_seconds=sum(s.duration_seconds for s in shots) or 10,
                continuity_patch=scene_patch or ContinuityPatch(),
                shots=shots,
            )
        ],
        created_at=now,
        updated_at=now,
    )


def test_ten_minute_feature_has_exact_frame_contiguous_sequence():
    project = _project([_shot(n) for n in range(1, 61)], fps=120)
    timeline = preflight_editorial_timeline(project)
    assert timeline.target_frames == 72000
    assert timeline.actual_frames == 72000
    assert timeline.frame_difference == 0
    assert len(timeline.clips) == 60
    assert timeline.warnings == ()
    assert timeline.clips[0].start_frame == 0
    assert timeline.clips[-1].end_frame == 72000
    assert all(
        left.end_frame == right.start_frame
        for left, right in zip(timeline.clips, timeline.clips[1:])
    )
    assert sum(clip.duration_frames for clip in timeline.clips) == 72000


def test_cumulative_rounding_avoids_clip_by_clip_drift():
    project = _project(
        [_shot(i, seconds=3.3333333333) for i in range(1, 4)],
        fps=24,
        target_seconds=10,
    )
    timeline = preflight_editorial_timeline(project)
    assert [(c.start_frame, c.end_frame) for c in timeline.clips] == [
        (0, 80),
        (80, 160),
        (160, 240),
    ]
    assert timeline.frame_difference == 0


def test_inherited_continuity_changes_report_names_without_exposing_values():
    original = ContinuityState(
        wardrobe={'style': 'green coat'},
        weather='sunny',
        freeform_notes={'cue': 'opening secret'},
    )
    project = _project(
        [
            _shot(1),
            _shot(2, continuity_patch=ContinuityPatch(wardrobe={'style': 'red coat'})),
            _shot(3, continuity_patch=ContinuityPatch(weather='storm')),
        ],
        target_seconds=30,
        bible=original,
    )
    timeline = preflight_editorial_timeline(project)
    assert timeline.clips[0].continuity_changed_fields == ()
    assert timeline.clips[1].continuity_changed_fields == ('wardrobe',)
    assert timeline.clips[2].continuity_changed_fields == ('wardrobe', 'weather')
    assert original.wardrobe == {'style': 'green coat'}
    report = str(timeline.to_dict())
    assert 'green coat' not in report
    assert 'red coat' not in report
    assert 'opening secret' not in report


def test_duration_mismatch_is_diagnostic_never_silently_stretched():
    project = _project([_shot(1, seconds=5)], target_seconds=10)
    timeline = preflight_editorial_timeline(project)
    assert timeline.target_frames == 240
    assert timeline.actual_frames == 120
    assert timeline.frame_difference == -120
    assert any('differs from project target' in w for w in timeline.warnings)


def test_too_short_to_make_frame_rejected():
    project = _project([_shot(1, seconds=0.001)], target_seconds=10)
    with pytest.raises(TimelineValidationError, match='no representable frame'):
        preflight_editorial_timeline(project)


def test_order_is_authored_order_not_ordinal_sorting():
    shots = [_shot(2, seconds=5), _shot(1, seconds=5)]
    project = _project(shots, target_seconds=10)
    timeline = preflight_editorial_timeline(project)
    assert [clip.shot_id for clip in timeline.clips] == [s.shot_id for s in shots]
    assert len([w for w in timeline.warnings if 'ordinal' in w]) == 2


def test_empty_project_is_not_misrepresented_as_ready():
    project = _project([], target_seconds=10)
    timeline = preflight_editorial_timeline(project)
    assert not timeline.clips
    assert timeline.actual_frames == 0
    assert timeline.frame_difference == -240
    assert 'Scene ' in timeline.warnings[0]


def test_output_is_json_compatible_and_snapshot_has_no_master_prompt():
    project = _project(
        [_shot(1, seconds=10, transition_out='hard cut')],
        target_seconds=10,
    )
    timeline = preflight_editorial_timeline(project)
    import json

    payload = json.dumps(timeline.to_dict())
    assert 'A cinematic sequence' not in payload
    assert timeline.clips[0].transition_out_declared is True
    assert 'hard cut' not in payload
    assert timeline.to_dict()['clips'][0]['duration_frames'] == 240
