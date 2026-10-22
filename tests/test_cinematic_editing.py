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


def test_integer_fps_timecodes_and_exact_seek_boundaries():
    project = _project(
        [_shot(1, seconds=5), _shot(2, seconds=5)],
        target_seconds=10,
        fps=120,
    )
    report = preflight_editorial_timeline(project)
    assert report.timecode_standard == 'integer-fps-non-drop'
    assert report.clips[0].start_timecode == '00:00:00:00'
    assert report.clips[0].end_timecode_exclusive == '00:00:05:00'
    assert report.clips[1].end_timecode_exclusive == '00:00:10:00'
    assert report.clip_at_frame(0).shot_id == project.scenes[0].shots[0].shot_id
    assert report.clip_at_frame(599).shot_id == project.scenes[0].shots[0].shot_id
    assert report.clip_at_frame(600).shot_id == project.scenes[0].shots[1].shot_id
    assert report.clip_at_frame(1199).shot_id == project.scenes[0].shots[1].shot_id
    for invalid in (-1, 1200, 1.5, True):
        with pytest.raises(IndexError):
            report.clip_at_frame(invalid)


def test_two_scene_spans_preserve_half_open_scene_boundaries():
    first_scene = _project(
        [_shot(1, seconds=3.3333333333), _shot(2, seconds=3.3333333333), _shot(3, seconds=3.3333333334)],
        target_seconds=15,
    )
    second_shot = _shot(4, seconds=5).model_copy(update={'ordinal': 1})
    second_scene = CinematicScene(
        scene_id='c' * 32, ordinal=2, title='Act two',
        target_duration_seconds=5, shots=[second_shot]
    )
    project = first_scene.model_copy(update={
        'scenes': first_scene.scenes + [second_scene]
    })
    report = preflight_editorial_timeline(project)
    assert len(report.scenes) == 2
    assert [(s.start_frame, s.end_frame, s.shot_count) for s in report.scenes] == [
        (0, 240, 3), (240, 360, 1),
    ]
    assert [(s.target_frames, s.frame_difference) for s in report.scenes] == [
        (240, 0), (120, 0),
    ]
    assert report.frame_difference == 0
    assert report.clips[-1].start_timecode == '00:00:10:00'
    assert report.clips[-1].end_timecode_exclusive == '00:00:15:00'


def test_metadata_digest_matches_independent_frame_oracle_contract():
    import hashlib
    import json

    project = _project([_shot(1, seconds=5), _shot(2, seconds=5)], target_seconds=10)
    report = preflight_editorial_timeline(project)
    identity = {
        'project_id': project.id,
        'project_revision': project.revision,
        'fps': 24,
        'target_frames': 240,
        'sequence': [
            [project.scenes[0].scene_id, project.scenes[0].shots[0].shot_id, 0, 120],
            [project.scenes[0].scene_id, project.scenes[0].shots[1].shot_id, 120, 240],
        ],
    }
    expected = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
        .encode('ascii')
    ).hexdigest()
    assert report.timeline_digest_sha256 == expected
    assert report.timeline_digest_sha256 == preflight_editorial_timeline(project).timeline_digest_sha256
    revised = project.model_copy(update={'revision': 9})
    assert preflight_editorial_timeline(revised).timeline_digest_sha256 != expected
    project.scenes[0].shots.reverse()
    assert preflight_editorial_timeline(project).timeline_digest_sha256 != expected


def test_fractional_hundred_clip_manifest_keeps_frames_and_scrubbing_contiguous():
    project = _project([_shot(i, seconds=0.1) for i in range(1, 101)], target_seconds=10)
    report = preflight_editorial_timeline(project)
    assert report.actual_frames == report.target_frames == 240
    assert not report.warnings
    assert sum(clip.duration_frames for clip in report.clips) == 240
    for frame in range(240):
        clip = report.clip_at_frame(frame)
        assert clip.start_frame <= frame < clip.end_frame
    assert report.clip_at_frame(239) == report.clips[-1]


def test_scene_budget_mismatch_and_empty_scene_are_diagnostics():
    project = _project([_shot(1, seconds=5)], target_seconds=10)
    scene = project.scenes[0].model_copy(update={'target_duration_seconds': 10})
    empty = CinematicScene(
        scene_id='c' * 32, ordinal=2, title='Unwritten',
        target_duration_seconds=10, shots=[],
    )
    project = project.model_copy(update={'scenes': [scene, empty]})
    report = preflight_editorial_timeline(project)
    assert report.scenes[0].frame_difference == -120
    assert report.scenes[1].shot_count == 0
    assert report.scenes[1].duration_frames == 0
    assert len(report.warnings) == 4  # both scene underfills, empty scene, project underfill
    assert any('contains no shots' in message for message in report.warnings)


def test_no_prompt_or_transition_value_leaks_to_edl_metadata():
    import json
    project = _project([
        _shot(1, seconds=10, transition_in='PRIVATE_DIALOGUE_778',
              transition_out='PRIVATE_SCRIPT_991',
              continuity_patch=ContinuityPatch(freeform_notes={'secret': 'PRIVATE_NOTE_123'}))
    ], target_seconds=10)
    report = preflight_editorial_timeline(project)
    payload = json.dumps(report.to_dict(), ensure_ascii=False)
    assert 'PRIVATE_' not in payload
    assert 'A cinematic sequence' not in payload
    assert 'A silent cinematic action' not in payload
    assert report.clips[0].transition_in_declared
    assert report.clips[0].transition_out_declared


def test_persisted_six_hundred_second_compiled_project_has_identical_edl_after_reload(monkeypatch, tmp_path):
    """Integration proof that the real service/compiler preserve an editorial EDL."""
    from app.video import cinematic_requests, cinematic_service
    from app.video.cinematic_models import ProjectCreateRequest

    monkeypatch.setenv('CHARACTER3D_STUDIO_WORKSPACE', str(tmp_path))
    original = cinematic_service.create_project(
        ProjectCreateRequest(
            title='Ten-minute filmed sequence',
            master_prompt='SCENE 1: Rooftop\nA traveler approaches the rooftop door.',
            target_duration_seconds=600,
            delivery_fps=120,
            delivery_resolution='2160p',
        )
    )
    compiled, diagnostics = cinematic_service.compile_project(
        original.id,
        cinematic_requests.CompileProjectRequest(
            expected_revision=original.revision,
            preferred_shot_seconds=9,
            engine_max_duration_seconds=9,
        ),
    )
    edl = preflight_editorial_timeline(compiled)
    assert diagnostics['shot_count'] == len(edl.clips) == 67
    assert len(edl.scenes) >= 1
    assert edl.actual_frames == edl.target_frames == 72000
    assert edl.frame_difference == 0
    assert edl.clips[-1].end_timecode_exclusive == '00:10:00:00'
    assert edl.timeline_digest_sha256 == preflight_editorial_timeline(
        cinematic_service.get_project(original.id)
    ).timeline_digest_sha256
    assert edl.clip_at_frame(71999) == edl.clips[-1]
    assert cinematic_service.get_project(original.id).revision == compiled.revision
