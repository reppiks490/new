"""Read-only cinematic revision impact planning.

Compares authoritative before/after project metadata and reports which shots
need fresh generation, which edits need re-compilation or assembly, and which
creative controls are not known to be honored by the current engine adapter.

Privacy: reports only opaque project/scene/shot IDs, stable reason codes and
counts. Prompts, reference IDs, continuity values and content hashes are NOT
included. This is a conservative advisory layer, NOT authority to reuse a job
or to submit one; actual source bytes, engine capabilities and project state
must be checked again by the owner-controlled execution layer.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from app.video.cinematic_models import merge_continuity

if TYPE_CHECKING:
    from app.video.cinematic_models import CinematicProject, CinematicScene, CinematicShot


class RevisionImpactError(ValueError):
    """Projects cannot be safely compared as versions of the same source."""


@dataclass(frozen=True)
class ShotRevisionImpact:
    shot_id: str
    previous_scene_id: str | None
    current_scene_id: str | None
    state: str
    requires_new_render: bool
    requires_creative_review: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class CinematicRevisionImpact:
    project_id: str
    before_revision: int
    after_revision: int
    requires_recompile: bool
    requires_master_reassembly: bool
    requires_creative_review: bool
    shots_requiring_render: int
    added_shots: int
    removed_shots: int
    reused_unchanged_shots: int
    changed_shots: int
    reason_codes: tuple[str, ...]
    shots: tuple[ShotRevisionImpact, ...]

    def to_dict(self) -> dict:
        """JSON-compatible IDs/counts/reason codes; never creative content."""
        return asdict(self)


def _index(project: 'CinematicProject') -> tuple[dict, tuple[str, ...]]:
    index: dict[str, tuple[CinematicScene, CinematicShot]] = {}
    order: list[str] = []
    scene_ids: set[str] = set()
    for scene in project.scenes:
        if scene.scene_id in scene_ids:
            raise RevisionImpactError('project contains duplicate scene IDs')
        scene_ids.add(scene.scene_id)
        for shot in scene.shots:
            if shot.shot_id in index:
                raise RevisionImpactError('project contains duplicate shot IDs')
            index[shot.shot_id] = (scene, shot)
            order.append(shot.shot_id)
    return index, tuple(order)


def _refs(project: 'CinematicProject', scene: 'CinematicScene', shot: 'CinematicShot') -> tuple[str, ...]:
    ids: list[str] = []
    seen: set[str] = set()
    for group in (
        project.reference_image_ids, scene.reference_image_ids, shot.reference_image_ids,
    ):
        for identifier in group:
            if identifier not in seen:
                seen.add(identifier)
                ids.append(identifier)
    return tuple(ids)


def _continuity(project: 'CinematicProject', scene: 'CinematicScene', shot: 'CinematicShot') -> dict:
    return merge_continuity(
        merge_continuity(project.continuity_bible, scene.continuity_patch),
        shot.continuity_patch,
    ).model_dump(mode='python')


def _codes_add(codes: list[str], reason: str) -> None:
    if reason not in codes:
        codes.append(reason)


def analyze_cinematic_revision(
    before: 'CinematicProject', after: 'CinematicProject'
) -> CinematicRevisionImpact:
    """Compute conservative shot-specific impact without touching records.

    Distinguishes a footage-affecting edit from reordered cuts and delivery-
    only changes. Project FPS or resolution conservatively invalidates all
    retained shots because generation settings can depend on the delivery
    profile, and no live capability snapshot is supplied. Reference list
    comparisons are metadata only and cannot detect changed bytes under a
    reused asset ID. New/edited creative controls not forwarded by the
    current VideoGenerationRequest adapter demand explicit creative review.
    """
    if not before.id or not after.id or before.id != after.id:
        raise RevisionImpactError('revision comparison needs the same persisted project ID')
    if type(before.revision) is not int or type(after.revision) is not int:
        raise RevisionImpactError('project revisions must be integers')
    if after.revision <= before.revision:
        raise RevisionImpactError('after revision must be newer than before revision')

    old, old_order = _index(before)
    new, new_order = _index(after)
    reasons: list[str] = []
    recompile = False
    assembly = False
    creative_review = False

    if before.master_prompt != after.master_prompt:
        _codes_add(reasons, 'MASTER_SCREENPLAY_CHANGED')
        recompile = True
    if before.target_duration_seconds != after.target_duration_seconds:
        _codes_add(reasons, 'PROJECT_TARGET_DURATION_CHANGED')
        recompile = True
    if before.delivery_fps != after.delivery_fps:
        _codes_add(reasons, 'PROJECT_DELIVERY_FPS_CHANGED')
    if before.delivery_resolution != after.delivery_resolution:
        _codes_add(reasons, 'PROJECT_DELIVERY_RESOLUTION_CHANGED')
    if before.aspect_ratio != after.aspect_ratio:
        _codes_add(reasons, 'PROJECT_ASPECT_RATIO_CHANGED')
    if old_order != new_order:
        _codes_add(reasons, 'SHOT_SEQUENCE_CHANGED')
        assembly = True

    old_scenes = {scene.scene_id: scene for scene in before.scenes}
    new_scenes = {scene.scene_id: scene for scene in after.scenes}
    if tuple(scene.scene_id for scene in before.scenes) != tuple(
        scene.scene_id for scene in after.scenes
    ):
        _codes_add(reasons, 'SCENE_SEQUENCE_CHANGED')
        assembly = True
    for sid in old_scenes.keys() & new_scenes.keys():
        a, b = old_scenes[sid], new_scenes[sid]
        if (
            a.source_text != b.source_text or a.synopsis != b.synopsis
            or a.target_duration_seconds != b.target_duration_seconds
            or a.title != b.title
        ):
            _codes_add(reasons, 'SCENE_SOURCE_OR_BUDGET_CHANGED')
            recompile = True
    if old_scenes.keys() != new_scenes.keys():
        recompile = True

    impacts: list[ShotRevisionImpact] = []
    added = removed = unchanged = changed = renders = 0
    # New timeline order first; removed shots remain available for audit after it.
    ordered_ids = tuple(new_order) + tuple(x for x in old_order if x not in new)
    for shot_id in ordered_ids:
        old_pair = old.get(shot_id)
        new_pair = new.get(shot_id)
        codes: list[str] = []
        if old_pair is None:
            added += 1
            renders += 1
            _codes_add(codes, 'SHOT_ADDED')
            impacts.append(ShotRevisionImpact(
                shot_id, None, new_pair[0].scene_id, 'added', True, False, tuple(codes),
            ))
            assembly = True
            continue
        if new_pair is None:
            removed += 1
            _codes_add(codes, 'SHOT_REMOVED')
            impacts.append(ShotRevisionImpact(
                shot_id, old_pair[0].scene_id, None, 'removed', False, False, tuple(codes),
            ))
            assembly = True
            continue

        old_scene, old_shot = old_pair
        new_scene, new_shot = new_pair
        rerender = False
        manual = False
        # Field-to-reason map mirrors the actual shot-generation controls
        # rather than metadata or latest-job bookkeeping.
        for field, reason in (
            ('prompt', 'SHOT_PROMPT_CHANGED'),
            ('negative_prompt', 'SHOT_NEGATIVE_PROMPT_CHANGED'),
            ('duration_seconds', 'SHOT_DURATION_CHANGED'),
            ('seed', 'SHOT_SEED_CHANGED'),
            ('engine_profile', 'SHOT_ENGINE_PROFILE_CHANGED'),
            ('camera_motion', 'SHOT_CAMERA_MOTION_CHANGED'),
            ('motion_strength', 'SHOT_MOTION_STRENGTH_CHANGED'),
        ):
            if getattr(old_shot, field) != getattr(new_shot, field):
                _codes_add(codes, reason)
                rerender = True
        if old_scene.scene_id != new_scene.scene_id:
            _codes_add(codes, 'SHOT_MOVED_TO_DIFFERENT_SCENE')
            rerender = True  # stored job linkage is scene-specific
        if _refs(before, old_scene, old_shot) != _refs(after, new_scene, new_shot):
            _codes_add(codes, 'EFFECTIVE_REFERENCE_SET_CHANGED')
            rerender = True
        if _continuity(before, old_scene, old_shot) != _continuity(after, new_scene, new_shot):
            _codes_add(codes, 'EFFECTIVE_CONTINUITY_CHANGED')
            rerender = True
        if before.delivery_fps != after.delivery_fps:
            _codes_add(codes, 'DELIVERY_FPS_MAY_CHANGE_GENERATION')
            rerender = True
        if before.delivery_resolution != after.delivery_resolution:
            _codes_add(codes, 'DELIVERY_RESOLUTION_MAY_CHANGE_GENERATION')
            rerender = True

        if (old_shot.lens_mm, old_shot.framing) != (new_shot.lens_mm, new_shot.framing):
            _codes_add(codes, 'UNFORWARDED_CREATIVE_CAMERA_CONTROLS_CHANGED')
            manual = True
        if (old_shot.transition_in, old_shot.transition_out) != (
            new_shot.transition_in, new_shot.transition_out
        ):
            _codes_add(codes, 'UNIMPLEMENTED_TRANSITION_INTENT_CHANGED')
            manual = True
        if old_shot.title != new_shot.title:
            _codes_add(codes, 'SHOT_TITLE_METADATA_CHANGED')
        if old_shot.ordinal != new_shot.ordinal:
            _codes_add(codes, 'SHOT_ORDINAL_METADATA_CHANGED')
        if old_order.index(shot_id) != new_order.index(shot_id):
            _codes_add(codes, 'SHOT_ORDER_CHANGED')

        if rerender:
            renders += 1
        if manual:
            creative_review = True
        if codes:
            changed += 1
        else:
            unchanged += 1
        impacts.append(ShotRevisionImpact(
            shot_id, old_scene.scene_id, new_scene.scene_id, 'changed' if codes else 'unchanged',
            rerender, manual, tuple(codes),
        ))
        if rerender or manual:
            assembly = True

    # Delivery settings, authored budgets and screenplay recompilation can
    # invalidate an assembled master without requiring every shot to render.
    if reasons or recompile or added or removed or changed:
        if any(c in reasons for c in (
            'PROJECT_TARGET_DURATION_CHANGED',
            'PROJECT_DELIVERY_FPS_CHANGED',
            'PROJECT_DELIVERY_RESOLUTION_CHANGED',
            'PROJECT_ASPECT_RATIO_CHANGED',
            'MASTER_SCREENPLAY_CHANGED',
            'SCENE_SOURCE_OR_BUDGET_CHANGED',
            'SCENE_SEQUENCE_CHANGED',
            'SHOT_SEQUENCE_CHANGED',
        )):
            assembly = True
    return CinematicRevisionImpact(
        project_id=after.id,
        before_revision=before.revision,
        after_revision=after.revision,
        requires_recompile=recompile,
        requires_master_reassembly=assembly,
        requires_creative_review=creative_review,
        shots_requiring_render=renders,
        added_shots=added,
        removed_shots=removed,
        reused_unchanged_shots=unchanged,
        changed_shots=changed,
        reason_codes=tuple(reasons),
        shots=tuple(impacts),
    )
