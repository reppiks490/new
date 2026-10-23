"""Non-destructive frame-exact director's-cut planning for cinematic projects.

A cut is an editorial *plan*: it neither mutates the project nor edits videos,
runs inference, requests FFmpeg, or asserts source footage exists. Each segment
references opaque source-shot IDs and frame offsets only. Cross-shot continuity
diagnostics reveal field names, never private values.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import asdict, dataclass
import hashlib
import json
from typing import TYPE_CHECKING, Sequence

from app.video.cinematic_editing import (
    EditorialTimeline,
    TimelineValidationError,
    preflight_editorial_timeline,
)
from app.video.cinematic_models import merge_continuity

if TYPE_CHECKING:
    from app.video.cinematic_models import CinematicProject, ContinuityState


@dataclass(frozen=True)
class CutSelection:
    """Select an interval within one planned clip, using local frame offsets."""

    shot_id: str
    source_in_frame: int = 0
    source_out_frame_exclusive: int | None = None


@dataclass(frozen=True)
class CutSegment:
    scene_id: str
    shot_id: str
    source_in_frame: int
    source_out_frame_exclusive: int
    edit_in_frame: int
    edit_out_frame_exclusive: int
    frame_count: int
    scene_changed: bool
    continuity_changed_fields: tuple[str, ...]
    transition_in_declared: bool
    transition_out_declared: bool


@dataclass(frozen=True)
class DirectorsCut:
    """Stable, privacy-neutral edit decisions linked to a project revision."""

    schema_version: int
    project_id: str
    project_revision: int
    fps: int
    source_timeline_digest_sha256: str
    cut_digest_sha256: str
    frame_count: int
    segments: tuple[CutSegment, ...]

    def to_dict(self) -> dict:
        """Return an archival, JSON-compatible metadata snapshot."""
        return asdict(self)

    def segment_at_frame(self, frame: int) -> CutSegment:
        """Binary-search a half-open cut interval; reject invalid frame seeks."""
        if type(frame) is not int or frame < 0 or frame >= self.frame_count:
            raise IndexError('frame position is outside the director cut')
        index = bisect_right(
            self.segments, frame, key=lambda segment: segment.edit_out_frame_exclusive
        )
        return self.segments[index]


def _changed_fields(
    before: 'ContinuityState | None', after: 'ContinuityState'
) -> tuple[str, ...]:
    if before is None:
        return ()
    older = before.model_dump(mode='python')
    newer = after.model_dump(mode='python')
    return tuple(key for key in newer if older[key] != newer[key])


def _cut_digest(
    timeline: EditorialTimeline, segments: Sequence[CutSegment]
) -> str:
    """Hash edit metadata, never raw prompts, asset paths or continuity values."""
    identity = {
        'schema_version': 1,
        'project_id': timeline.project_id,
        'project_revision': timeline.project_revision,
        'fps': timeline.delivery_fps,
        'source_timeline_digest_sha256': timeline.timeline_digest_sha256,
        'segments': [
            [s.scene_id, s.shot_id, s.source_in_frame, s.source_out_frame_exclusive]
            for s in segments
        ],
    }
    payload = json.dumps(identity, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return hashlib.sha256(payload.encode('ascii')).hexdigest()


def plan_directors_cut(
    project: 'CinematicProject',
    selections: Sequence[CutSelection],
    *,
    source_timeline: EditorialTimeline | None = None,
) -> DirectorsCut:
    """Plan frame-exact trims, repeats and reordering without touching source state.

    This operates on delivery frame positions, not media timestamps. Native
    generation FPS may differ. Cutting a planned shot is NOT proof that its
    rendered file exists, has matching native FPS, or is safe to assemble.

    `source_timeline` is an optional precomputed EDL; mismatched revisions,
    digests, FPS, or IDs are rejected to prevent using an obsolete snapshot.
    """
    timeline = source_timeline or preflight_editorial_timeline(project)
    if source_timeline is not None:
        current = preflight_editorial_timeline(project)
        if timeline != current:
            raise TimelineValidationError('source editorial timeline does not match project')
    if not selections:
        raise TimelineValidationError('director cut requires at least one shot selection')
    if not timeline.clips:
        raise TimelineValidationError('source editorial timeline has no shots')

    shots = {clip.shot_id: clip for clip in timeline.clips}
    states: dict[str, ContinuityState] = {}
    for scene in project.scenes:
        parent_state = merge_continuity(project.continuity_bible, scene.continuity_patch)
        for shot in scene.shots:
            states[shot.shot_id] = merge_continuity(parent_state, shot.continuity_patch)

    result: list[CutSegment] = []
    cursor = 0
    previous_scene: str | None = None
    previous_state: ContinuityState | None = None

    for selection in selections:
        if not isinstance(selection, CutSelection):
            raise TimelineValidationError('director cut entries must be CutSelection values')
        clip = shots.get(selection.shot_id)
        if clip is None:
            raise TimelineValidationError('director cut references an unknown shot ID')
        source_in = selection.source_in_frame
        source_out = (
            clip.duration_frames
            if selection.source_out_frame_exclusive is None
            else selection.source_out_frame_exclusive
        )
        if (
            type(source_in) is not int
            or type(source_out) is not int
            or not 0 <= source_in < source_out <= clip.duration_frames
        ):
            raise TimelineValidationError('cut bounds must be whole frames within the source clip')
        frames = source_out - source_in
        state = states[selection.shot_id]
        result.append(
            CutSegment(
                scene_id=clip.scene_id,
                shot_id=clip.shot_id,
                source_in_frame=source_in,
                source_out_frame_exclusive=source_out,
                edit_in_frame=cursor,
                edit_out_frame_exclusive=cursor + frames,
                frame_count=frames,
                scene_changed=previous_scene is not None and previous_scene != clip.scene_id,
                continuity_changed_fields=_changed_fields(previous_state, state),
                transition_in_declared=clip.transition_in_declared and source_in == 0,
                transition_out_declared=(
                    clip.transition_out_declared and source_out == clip.duration_frames
                ),
            )
        )
        previous_state = state
        previous_scene = clip.scene_id
        cursor += frames

    if not project.id:
        raise TimelineValidationError('project must be persisted')
    return DirectorsCut(
        schema_version=1,
        project_id=timeline.project_id,
        project_revision=timeline.project_revision,
        fps=timeline.delivery_fps,
        source_timeline_digest_sha256=timeline.timeline_digest_sha256,
        cut_digest_sha256=_cut_digest(timeline, result),
        frame_count=cursor,
        segments=tuple(result),
    )


def verify_directors_cut(
    project: 'CinematicProject', cut: DirectorsCut
) -> None:
    """Verify archived cut metadata by recomputing it from the current project.

    Detects stale revisions, altered shot bounds, frame arithmetic, scene/
    continuity flags and forged or corrupted cut digests. This is deterministic
    project-metadata validation, not cryptographic proof of actual media bytes
    or a digital signature. Returns None only if the snapshot matches.
    """
    if not isinstance(cut, DirectorsCut) or cut.schema_version != 1:
        raise TimelineValidationError('unsupported director cut snapshot schema')
    if not cut.segments:
        raise TimelineValidationError('director cut snapshot has no segments')
    selections = [
        CutSelection(
            shot_id=segment.shot_id,
            source_in_frame=segment.source_in_frame,
            source_out_frame_exclusive=segment.source_out_frame_exclusive,
        )
        for segment in cut.segments
    ]
    expected = plan_directors_cut(project, selections)
    if cut != expected:
        raise TimelineValidationError(
            'director cut snapshot does not match current project metadata'
        )


def restore_directors_cut(
    project: 'CinematicProject', snapshot: dict
) -> DirectorsCut:
    """Safely restore JSON-decoded metadata against authoritative project state.

    No untrusted serialized dataclass is accepted verbatim. Shot identifiers
    and local cut ranges are extracted, the entire cut is reconstructed from
    the current project, and every serialized field must match the canonical
    regenerated form. Unknown keys, stale revisions, changed annotations,
    forged hashes, invalid bounds and non-JSON-native representations fail.
    This is a metadata conformance check, never media authenticity proof.
    """
    if type(snapshot) is not dict or type(snapshot.get('schema_version')) is not int:
        raise TimelineValidationError('director cut snapshot has an invalid schema')
    if snapshot['schema_version'] != 1:
        raise TimelineValidationError('unsupported director cut snapshot schema')

    segments = snapshot.get('segments')
    if type(segments) is not list or not segments:
        raise TimelineValidationError('director cut snapshot needs a nonempty segments array')
    selected: list[CutSelection] = []
    for item in segments:
        if type(item) is not dict:
            raise TimelineValidationError('director cut snapshot has an invalid segment')
        shot_id = item.get('shot_id')
        start = item.get('source_in_frame')
        end = item.get('source_out_frame_exclusive')
        if (
            type(shot_id) is not str
            or type(start) is not int
            or type(end) is not int
        ):
            raise TimelineValidationError('director cut snapshot has invalid source offsets')
        selected.append(CutSelection(shot_id, start, end))
    regenerated = plan_directors_cut(project, selected)
    # JSON transforms dataclass tuple fields into arrays. Compare the precise
    # serialized representation, so hidden extra keys or altered flags fail.
    canonical = json.loads(json.dumps(regenerated.to_dict()))
    try:
        candidate_wire = json.dumps(
            snapshot, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False
        )
        canonical_wire = json.dumps(
            canonical, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise TimelineValidationError('director cut snapshot is not valid JSON metadata') from exc
    # Python considers False == 0 and True == 1; wire-level canonical
    # comparison must reject JSON boolean-for-integer type confusion.
    if candidate_wire != canonical_wire:
        raise TimelineValidationError(
            'director cut snapshot does not match current project metadata'
        )
    return regenerated
