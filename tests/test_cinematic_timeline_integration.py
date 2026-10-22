"""Independent cinematic timeline QA: no media inference, no paid adapters.

The frame oracle and tests live here rather than modifying the concurrently
owned production compiler, rendering service, UI or API.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from types import SimpleNamespace
from typing import Any
import hashlib
import json
import pytest


class TimelineFrameError(ValueError):
    """A project cannot be accounted for without losing at least one frame."""


def _positive_seconds(value: Any, *, label: str) -> Decimal:
    try:
        seconds = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise TimelineFrameError(f'{label} must be finite positive seconds') from exc
    if not seconds.is_finite() or seconds <= 0:
        raise TimelineFrameError(f'{label} must be finite positive seconds')
    return seconds


def _nearest_frame(seconds: Decimal, fps: int) -> int:
    return int((seconds * fps).to_integral_value(rounding=ROUND_HALF_UP))


def _timecode(frame: int, fps: int) -> str:
    seconds, subframe = divmod(frame, fps)
    minutes, sec = divmod(seconds, 60)
    hours, minute = divmod(minutes, 60)
    return f'{hours:02d}:{minute:02d}:{sec:02d}:{subframe:02d}'


def build_timeline_manifest(project: Any) -> dict[str, Any]:
    """QA-only deterministic half-open frame intervals with private text omitted.

    Round cumulative exact decimal duration, never each shot individually.
    Timecodes assume integer non-drop frame rates; they are not SMPTE drop-frame.
    The manifest is a test oracle, NOT evidence that footage exists or plays.
    """
    fps = getattr(project, 'delivery_fps', None)
    if type(fps) is not int or not 1 <= fps <= 120:
        raise TimelineFrameError('delivery_fps must be an integer from 1 to 120')
    project_id = getattr(project, 'id', None)
    if (
        not isinstance(project_id, str)
        or len(project_id) != 32
        or any(c not in '0123456789abcdef' for c in project_id)
    ):
        raise TimelineFrameError('project must have a persisted lowercase hexadecimal ID')
    revision = getattr(project, 'revision', None)
    if type(revision) is not int or revision < 1:
        raise TimelineFrameError('project revision must be a positive integer')
    target_seconds = _positive_seconds(project.target_duration_seconds, label='project target')
    if not project.scenes:
        raise TimelineFrameError('cannot create a timeline without scenes')

    sequence: list[dict[str, Any]] = []
    scene_spans: list[dict[str, Any]] = []
    cumulative_seconds = Decimal(0)
    next_frame = 0
    seen_scene_ids: set[str] = set()
    seen_shot_ids: set[str] = set()

    for scene_index, scene in enumerate(project.scenes, start=1):
        if scene.scene_id in seen_scene_ids:
            raise TimelineFrameError('duplicate scene IDs')
        seen_scene_ids.add(scene.scene_id)
        if not scene.shots:
            raise TimelineFrameError(f'scene {scene_index} has no shots')
        scene_start = next_frame
        scene_seconds = Decimal(0)
        for shot_index, shot in enumerate(scene.shots, start=1):
            if shot.shot_id in seen_shot_ids:
                raise TimelineFrameError('duplicate shot IDs')
            seen_shot_ids.add(shot.shot_id)
            seconds = _positive_seconds(
                shot.duration_seconds, label=f'scene {scene_index} shot {shot_index}'
            )
            cumulative_seconds += seconds
            scene_seconds += seconds
            end = _nearest_frame(cumulative_seconds, fps)
            if end <= next_frame:
                raise TimelineFrameError(
                    f'scene {scene_index} shot {shot_index} has less than one representable frame'
                )
            sequence.append({
                'scene_index': scene_index,
                'shot_index': shot_index,
                'scene_id': scene.scene_id,
                'shot_id': shot.shot_id,
                'in_frame': next_frame,
                'out_frame_exclusive': end,
                'frame_count': end - next_frame,
                'in_timecode': _timecode(next_frame, fps),
                'out_timecode_exclusive': _timecode(end, fps),
                'linked_job_id': shot.latest_job_id,
                'rendered_project_revision': shot.latest_rendered_project_revision,
            })
            next_frame = end
        scene_spans.append({
            'scene_index': scene_index,
            'scene_id': scene.scene_id,
            'in_frame': scene_start,
            'out_frame_exclusive': next_frame,
            'frame_count': next_frame - scene_start,
            'shot_count': len(scene.shots),
            'planned_seconds': str(scene_seconds),
        })

    target_frames = _nearest_frame(target_seconds, fps)
    delta = next_frame - target_frames
    identity = {
        'project_id': project_id,
        'project_revision': revision,
        'fps': fps,
        'target_frames': target_frames,
        'sequence': [
            [item['scene_id'], item['shot_id'], item['in_frame'], item['out_frame_exclusive']]
            for item in sequence
        ],
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')
    ).hexdigest()
    return {
        'schema_version': 1,
        'project_id': project_id,
        'project_revision': revision,
        'frames_per_second': fps,
        'timecode_standard': 'integer-fps-non-drop',
        'total_scenes': len(scene_spans),
        'total_shots': len(sequence),
        'timeline_frames': next_frame,
        'timeline_seconds': str(cumulative_seconds),
        'delivery_target_frames': target_frames,
        'target_alignment_delta_frames': delta,
        'target_aligned': delta == 0,
        'timeline_digest_sha256': digest,
        'scenes': scene_spans,
        'shots': sequence,
    }


def _project(durations=(3.333333333333, 3.333333333333, 3.333333333334), *, fps=24, target=10):
    shots = [
        SimpleNamespace(
            shot_id=f'{index + 20:032x}', duration_seconds=value,
            latest_job_id=None, latest_rendered_project_revision=None,
            prompt='SECRET SCRIPT', continuity_patch='SECRET CONTINUITY',
        )
        for index, value in enumerate(durations)
    ]
    return SimpleNamespace(
        id='1' * 32, revision=2, delivery_fps=fps,
        target_duration_seconds=target,
        scenes=[SimpleNamespace(scene_id='2' * 32, shots=shots)],
        master_prompt='MASTER SECRET',
    )


def test_frame_oracle_has_no_gaps_and_reproducible_digest():
    project = _project()
    first = build_timeline_manifest(project)
    assert first == build_timeline_manifest(project)
    assert first['timeline_frames'] == first['delivery_target_frames'] == 240
    assert first['target_aligned'] is True
    assert [(shot['in_frame'], shot['out_frame_exclusive']) for shot in first['shots']] == [
        (0, 80), (80, 160), (160, 240)
    ]
    assert first['shots'][-1]['out_timecode_exclusive'] == '00:00:10:00'


def test_fractional_shots_do_not_accumulate_rounding_drift():
    result = build_timeline_manifest(_project((0.1,) * 100, target=10))
    assert result['timeline_frames'] == 240
    assert all(item['frame_count'] > 0 for item in result['shots'])
    assert sum(item['frame_count'] for item in result['shots']) == 240


def test_mismatch_reported_not_concealed():
    result = build_timeline_manifest(_project((2, 3), target=10, fps=30))
    assert result['target_alignment_delta_frames'] == -150
    assert result['target_aligned'] is False


def test_too_short_shot_fails_explicitly():
    with pytest.raises(TimelineFrameError, match='less than one representable frame'):
        build_timeline_manifest(_project((0.001, 10)))


def test_invalid_fps_and_nonfinite_duration_rejected():
    with pytest.raises(TimelineFrameError, match='delivery_fps'):
        build_timeline_manifest(_project(fps=0))
    with pytest.raises(TimelineFrameError, match='finite positive'):
        build_timeline_manifest(_project((float('nan'),)))


def test_duplicate_shot_identifiers_rejected():
    project = _project((5, 5))
    project.scenes[0].shots[1].shot_id = project.scenes[0].shots[0].shot_id
    with pytest.raises(TimelineFrameError, match='duplicate shot'):
        build_timeline_manifest(project)


def test_manifest_is_private_and_does_not_mutate_project():
    project = _project()
    old = deepcopy(project)
    rendered = json.dumps(build_timeline_manifest(project))
    assert project == old
    assert 'SECRET' not in rendered


def test_revision_and_order_change_digest():
    project = _project()
    before = build_timeline_manifest(project)['timeline_digest_sha256']
    project.revision += 1
    after_revision = build_timeline_manifest(project)['timeline_digest_sha256']
    project.scenes[0].shots.reverse()
    after_order = build_timeline_manifest(project)['timeline_digest_sha256']
    assert len({before, after_revision, after_order}) == 3


def test_real_compiler_600_seconds_67_shots_and_restart_recovery(monkeypatch, tmp_path):
    # Integration: project DB + real compiler + read-after-write + optimistic revisions.
    from app.video import cinematic_models as models
    from app.video import cinematic_requests as requests
    from app.video import cinematic_service as service

    monkeypatch.setenv('CHARACTER3D_STUDIO_WORKSPACE', str(tmp_path))
    project = service.create_project(models.ProjectCreateRequest(
        title='600 second QA film',
        master_prompt='SCENE 1: Arrival\nA traveler enters an unfamiliar city.',
        target_duration_seconds=600,
        delivery_fps=24,
        delivery_resolution='1080p',
    ))
    compiled, diagnostics = service.compile_project(
        project.id,
        requests.CompileProjectRequest(
            expected_revision=1, preferred_shot_seconds=9,
            engine_max_duration_seconds=9,
        ),
    )
    assert diagnostics['shot_count'] == 67
    report = build_timeline_manifest(compiled)
    assert report['total_shots'] == 67
    assert report['timeline_frames'] == 14_400
    assert report['delivery_target_frames'] == 14_400
    assert report['target_aligned'] is True
    assert build_timeline_manifest(service.get_project(project.id)) == report
    with pytest.raises(service.ProjectRevisionConflict):
        service.compile_project(project.id, requests.CompileProjectRequest(expected_revision=1))
    assert service.get_project(project.id).revision == compiled.revision


def test_real_max_length_prompt_compiler_is_deterministic(monkeypatch, tmp_path):
    from app.video import cinematic_compiler as compiler
    from app.video import cinematic_models as models
    from app.video import cinematic_service as service

    monkeypatch.setenv('CHARACTER3D_STUDIO_WORKSPACE', str(tmp_path))
    prompt = ('A long cinematic scene unfolds. ' * 3200)[:100_000]
    project = service.create_project(models.ProjectCreateRequest(
        title='QA long screenplay', master_prompt=prompt,
        target_duration_seconds=600, delivery_fps=24,
    ))
    result = compiler.compile_project_prompt(
        project, preferred_shot_seconds=10, engine_max_duration_seconds=10
    )
    again = compiler.compile_project_prompt(
        project, preferred_shot_seconds=10, engine_max_duration_seconds=10
    )
    assert result.scenes == again.scenes
    assert sum(len(scene.shots) for scene in result.scenes) >= 60
    assert all(len(shot.prompt) <= 20_000 for scene in result.scenes for shot in scene.shots)
    assert abs(
        sum(shot.duration_seconds for scene in result.scenes for shot in scene.shots) - 600
    ) < 0.01
