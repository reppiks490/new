"""QA36: current scoped continuity semantics and privacy-safe reset audit.

No media, engine inference, owner files, network or GPU are used.
These tests document observed behavior; they do not mandate carry-forward.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.video.cinematic_continuity_scope_qa36 import audit_implicit_continuity_resets
from app.video.cinematic_editing import preflight_editorial_timeline
from app.video.cinematic_models import (
    CinematicProject,
    CinematicScene,
    CinematicShot,
    ContinuityPatch,
    ContinuityState,
)
from app.video.cinematic_service import resolve_effective_continuity


def _shot(n: int, patch: ContinuityPatch | None = None) -> CinematicShot:
    return CinematicShot(
        shot_id=f'{n:032x}',
        ordinal=n,
        title='Synthetic shot',
        prompt='Private scripted sequence, not for diagnostics.',
        duration_seconds=5,
        continuity_patch=patch or ContinuityPatch(),
    )


def _scene(n: int, shots: list[CinematicShot], patch: ContinuityPatch | None = None) -> CinematicScene:
    return CinematicScene(
        scene_id=f'{100 + n:032x}',
        ordinal=n,
        title='Synthetic scene',
        target_duration_seconds=sum(shot.duration_seconds for shot in shots),
        shots=shots,
        continuity_patch=patch or ContinuityPatch(),
    )


def _project(scenes: list[CinematicScene], bible: ContinuityState | None = None) -> CinematicProject:
    now = datetime(2026, 10, 24, tzinfo=timezone.utc)
    return CinematicProject(
        id='a' * 32,
        revision=3,
        title='Synthetic private project',
        master_prompt='Private screenplay; must not appear in QA output.',
        target_duration_seconds=max(10, sum(
            shot.duration_seconds for scene in scenes for shot in scene.shots
        )),
        delivery_fps=24,
        delivery_resolution='480p',
        aspect_ratio='16:9',
        continuity_bible=bible or ContinuityState(),
        scenes=scenes,
        created_at=now,
        updated_at=now,
    )


def test_shot_patch_reverts_to_scene_baseline_without_explicit_followup_patch():
    shots = [
        _shot(1, ContinuityPatch(wardrobe={'color': 'private scarlet'})),
        _shot(2),
    ]
    project = _project(
        [_scene(1, shots)],
        ContinuityState(wardrobe={'color': 'private azure'}),
    )
    actual = resolve_effective_continuity(project, project.scenes[0], shots[1])
    assert actual.wardrobe == {'color': 'private azure'}

    report = audit_implicit_continuity_resets(project)
    assert report['potential_reset_count'] == 1
    assert report['potential_resets'] == [{
        'scene_id': project.scenes[0].scene_id,
        'shot_id': shots[1].shot_id,
        'scope': 'shot_boundary',
        'field_names': ['wardrobe'],
    }]
    timeline = preflight_editorial_timeline(project)
    assert timeline.clips[1].continuity_changed_fields == ('wardrobe',)


def test_scene_patch_reverts_to_project_bible_at_next_scene():
    first = _scene(1, [_shot(1)], ContinuityPatch(weather='private storm'))
    second = _scene(2, [_shot(2)])
    project = _project([first, second], ContinuityState(weather='private sunshine'))
    assert resolve_effective_continuity(project, second, second.shots[0]).weather == 'private sunshine'

    report = audit_implicit_continuity_resets(project)
    assert report['potential_reset_count'] == 1
    assert report['potential_resets'][0]['scope'] == 'scene_boundary'
    assert report['potential_resets'][0]['field_names'] == ['weather']


def test_explicit_next_shot_override_is_not_called_implicit_reset():
    shots = [
        _shot(1, ContinuityPatch(wardrobe='private red')),
        _shot(2, ContinuityPatch(wardrobe='private green')),
        _shot(3, ContinuityPatch(wardrobe='private blue')),
    ]
    project = _project([_scene(1, shots)], ContinuityState(wardrobe='private white'))
    report = audit_implicit_continuity_resets(project)
    assert report['potential_reset_count'] == 0
    assert report['potential_resets'] == []


def test_explicit_scene_override_is_not_called_implicit_reset():
    first = _scene(1, [_shot(1)], ContinuityPatch(weather='private storm'))
    second = _scene(2, [_shot(2)], ContinuityPatch(weather='private fog'))
    project = _project([first, second], ContinuityState(weather='private sunshine'))
    assert audit_implicit_continuity_resets(project)['potential_reset_count'] == 0


def test_freeform_note_reset_is_reported_without_values_or_mutation():
    shots = [
        _shot(1, ContinuityPatch(freeform_notes={'cue': 'private one-time secret'})),
        _shot(2),
    ]
    project = _project(
        [_scene(1, shots)],
        ContinuityState(freeform_notes={'baseline': 'private permanent secret'}),
    )
    before = project.model_dump(mode='json')
    report = audit_implicit_continuity_resets(project)
    assert project.model_dump(mode='json') == before
    assert report['potential_reset_count'] == 1
    assert report['potential_resets'][0]['field_names'] == ['freeform_notes']
    serialized = str(report)
    for forbidden in (
        'private one-time secret',
        'private permanent secret',
        'Private screenplay',
        'Private scripted sequence',
        'private project',
    ):
        assert forbidden not in serialized


def test_unchanged_baseline_is_not_a_false_positive():
    project = _project(
        [_scene(1, [_shot(1), _shot(2)])],
        ContinuityState(wardrobe='private constant'),
    )
    report = audit_implicit_continuity_resets(project)
    assert report['potential_reset_count'] == 0
    assert report['advisory_only'] is True
