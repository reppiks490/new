"""Preview archival director's cuts against a changed cinematic project.

This is a metadata-only, fail-closed migration *preview*. It never repairs
render records, changes a stored project, alters cut snapshots, or approves
existing footage for reuse. Even a portable selection must pass execution-time
asset-byte and render-input provenance gates before a media conform operation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import TYPE_CHECKING

from app.video.cinematic_directors_cut import (
    CutSelection,
    DirectorsCut,
    plan_directors_cut,
    restore_directors_cut,
)
from app.video.cinematic_editing import preflight_editorial_timeline
from app.video.cinematic_revision_impact import (
    RevisionImpactError,
    analyze_cinematic_revision,
)

if TYPE_CHECKING:
    from app.video.cinematic_models import CinematicProject


@dataclass(frozen=True)
class CutMigrationSegment:
    segment_index: int
    shot_id: str
    status: str  # portable / review_required / blocked
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class CutMigrationPreview:
    project_id: str
    from_revision: int
    to_revision: int
    status: str  # portable / review_required / blocked
    portable_segments: int
    review_segments: int
    blocked_segments: int
    segments: tuple[CutMigrationSegment, ...]
    proposed_cut: DirectorsCut | None

    def to_dict(self) -> dict:
        """Produce privacy-neutral JSON-compatible diagnostics."""
        return asdict(self)


def preview_directors_cut_migration(
    previous_project: 'CinematicProject',
    current_project: 'CinematicProject',
    saved_cut: DirectorsCut,
) -> CutMigrationPreview:
    """Assess whether archived, frame-offset cut decisions survive a revision.

    A portable result means selections are structurally reusable in the newer
    *editorial plan*, NOT that previous media bytes remain valid. Review means
    the cut can be represented but source-generation creative intent may have
    changed; the caller must require human review and fresh provenance. Blocked
    means offsets cannot be carried across safely, e.g., FPS change, deletion
    of a selected shot, or a selected frame exceeding its new source duration.

    The original cut must match the exact old project. A damaged/forged old
    archive is rejected, not treated as a salvageable trusted edit.
    """
    if not isinstance(saved_cut, DirectorsCut):
        raise RevisionImpactError('archived cut must be a DirectorsCut')
    # Roundtrip forces canonical JSON field types (True != 1) and refuses
    # arbitrary extra metadata. It does not accept a different old revision.
    old_cut = restore_directors_cut(
        previous_project, json.loads(json.dumps(saved_cut.to_dict(), allow_nan=False))
    )
    impact = analyze_cinematic_revision(previous_project, current_project)
    current_timeline = preflight_editorial_timeline(current_project)
    source_clips = {clip.shot_id: clip for clip in current_timeline.clips}
    by_shot = {shot.shot_id: shot for shot in impact.shots}
    fps_changed = old_cut.fps != current_timeline.delivery_fps

    migrated: list[CutMigrationSegment] = []
    selections: list[CutSelection] = []
    for index, segment in enumerate(old_cut.segments):
        reasons: list[str] = []
        clip = source_clips.get(segment.shot_id)
        shot_impact = by_shot.get(segment.shot_id)
        if fps_changed:
            reasons.append('FRAME_RATE_CHANGED')
        if clip is None or shot_impact is None or shot_impact.state == 'removed':
            reasons.append('SOURCE_SHOT_REMOVED')
        elif (
            segment.source_in_frame >= clip.duration_frames
            or segment.source_out_frame_exclusive > clip.duration_frames
        ):
            reasons.append('TRIM_EXCEEDS_NEW_SOURCE')
        blocked = bool(reasons)
        if not blocked:
            if shot_impact.requires_new_render:
                reasons.append('SOURCE_RENDER_INPUT_CHANGED')
            if shot_impact.requires_creative_review:
                reasons.append('SOURCE_CREATIVE_INTENT_CHANGED')
            if impact.requires_recompile:
                reasons.append('COMPILATION_REVIEW_REQUIRED')
            if previous_project.aspect_ratio != current_project.aspect_ratio:
                reasons.append('FINISHING_ASPECT_RATIO_CHANGED')
            selections.append(CutSelection(
                segment.shot_id, segment.source_in_frame,
                segment.source_out_frame_exclusive,
            ))
        status = 'blocked' if blocked else ('review_required' if reasons else 'portable')
        migrated.append(CutMigrationSegment(index, segment.shot_id, status, tuple(reasons)))

    blocked_count = sum(item.status == 'blocked' for item in migrated)
    review_count = sum(item.status == 'review_required' for item in migrated)
    portable_count = len(migrated) - blocked_count - review_count
    proposed = (
        plan_directors_cut(current_project, selections, source_timeline=current_timeline)
        if not blocked_count else None
    )
    status = 'blocked' if blocked_count else ('review_required' if review_count else 'portable')
    return CutMigrationPreview(
        project_id=impact.project_id,
        from_revision=impact.before_revision,
        to_revision=impact.after_revision,
        status=status,
        portable_segments=portable_count,
        review_segments=review_count,
        blocked_segments=blocked_count,
        segments=tuple(migrated),
        proposed_cut=proposed,
    )
