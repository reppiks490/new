"""Frame-accurate, side-effect-free editorial preflight for cinematic projects.

This module prepares an edit decision list (EDL), not a rendered master. It
never reads media, exposes prompt text, or guesses whether a shot was rendered.
The project sequence is authoritative; ordinal fields are diagnostic only.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
from typing import TYPE_CHECKING, Any

from app.video.cinematic_models import merge_continuity

if TYPE_CHECKING:
    from app.video.cinematic_models import CinematicProject, ContinuityState


class TimelineValidationError(ValueError):
    """The stored shot timeline cannot be represented as valid delivery frames."""


@dataclass(frozen=True)
class EditorialClip:
    scene_id: str
    shot_id: str
    scene_index: int
    shot_index: int
    start_frame: int
    end_frame: int
    duration_frames: int
    start_timecode: str
    end_timecode_exclusive: str
    continuity_changed_fields: tuple[str, ...]
    transition_in_declared: bool
    transition_out_declared: bool


@dataclass(frozen=True)
class EditorialSceneSpan:
    scene_id: str
    scene_index: int
    start_frame: int
    end_frame: int
    duration_frames: int
    target_frames: int
    frame_difference: int
    shot_count: int


@dataclass(frozen=True)
class EditorialTimeline:
    project_id: str
    project_revision: int
    delivery_fps: int
    target_frames: int
    actual_frames: int
    frame_difference: int
    timecode_standard: str
    timeline_digest_sha256: str
    scenes: tuple[EditorialSceneSpan, ...]
    clips: tuple[EditorialClip, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible snapshot containing identifiers, not prompts."""
        return asdict(self)

    def clip_at_frame(self, frame: int) -> EditorialClip:
        """Locate a clip at a half-open delivery-frame position for scrubbing.

        Raises IndexError for frame positions outside populated film footage.
        It does not inspect video files or claim that a clip was rendered.
        """
        if type(frame) is not int or frame < 0 or frame >= self.actual_frames:
            raise IndexError('frame position is outside the editorial timeline')
        index = bisect_right([clip.end_frame for clip in self.clips], frame)
        if index >= len(self.clips):
            raise IndexError('frame position has no associated clip')
        return self.clips[index]


def _seconds(value: object, description: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise TimelineValidationError(f'{description} has an invalid duration') from exc
    if not result.is_finite() or result <= 0:
        raise TimelineValidationError(f'{description} needs a finite positive duration')
    return result


def _round_frames(seconds: Decimal, fps: int) -> int:
    return int((seconds * fps).to_integral_value(rounding=ROUND_HALF_UP))


def _timecode(frame: int, fps: int) -> str:
    """Express a frame offset in integer-FPS non-drop timecode."""
    total_seconds, subframe = divmod(frame, fps)
    total_minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(total_minutes, 60)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}:{subframe:02d}'


def _timeline_digest(project_id: str, revision: int, fps: int, target: int, clips: list[EditorialClip]) -> str:
    """Compute the same public-field sequence identity as Helper 4's QA oracle."""
    identity = {
        'project_id': project_id,
        'project_revision': revision,
        'fps': fps,
        'target_frames': target,
        'sequence': [
            [clip.scene_id, clip.shot_id, clip.start_frame, clip.end_frame]
            for clip in clips
        ],
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return hashlib.sha256(encoded.encode('ascii')).hexdigest()


def _changed_fields(before: 'ContinuityState | None', after: 'ContinuityState') -> tuple[str, ...]:
    if before is None:
        return ()
    left = before.model_dump(mode='python')
    right = after.model_dump(mode='python')
    return tuple(field for field in right if left[field] != right[field])


def preflight_editorial_timeline(project: 'CinematicProject') -> EditorialTimeline:
    """Compile a sequential shot graph to a frame-exact EDL with safe diagnostics.

    Frame boundaries are rounded from *cumulative* time, not independently
    rounded clip durations. This prevents accumulated drift in long films.
    Transitions are metadata only: no overlap or frame blending is implied.
    A mismatched target is reported, not concealed by changing a shot's length.
    """
    fps = project.delivery_fps
    if type(fps) is not int or not 1 <= fps <= 120:
        raise TimelineValidationError('delivery_fps must be an integer from 1 to 120')
    if not project.id:
        raise TimelineValidationError('project must have a persisted identifier')

    target_frames = _round_frames(
        _seconds(project.target_duration_seconds, 'project'), fps
    )
    warnings: list[str] = []
    clips: list[EditorialClip] = []
    scene_spans: list[EditorialSceneSpan] = []
    cumulative = Decimal(0)
    previous_state = None

    if not project.scenes:
        warnings.append('Project contains no scenes')

    for scene_index, scene in enumerate(project.scenes, start=1):
        if scene.ordinal != scene_index:
            warnings.append(f'Scene {scene.scene_id} ordinal does not match sequence position')
        if not scene.shots:
            warnings.append(f'Scene {scene.scene_id} contains no shots')
        scene_total = Decimal(0)
        scene_start_frame = _round_frames(cumulative, fps)
        scene_continuity = merge_continuity(project.continuity_bible, scene.continuity_patch)

        for shot_index, shot in enumerate(scene.shots, start=1):
            if shot.ordinal != shot_index:
                warnings.append(f'Shot {shot.shot_id} ordinal does not match sequence position')
            duration = _seconds(shot.duration_seconds, f'shot {shot.shot_id}')
            start = _round_frames(cumulative, fps)
            cumulative += duration
            scene_total += duration
            end = _round_frames(cumulative, fps)
            if end <= start:
                raise TimelineValidationError(
                    f'Shot {shot.shot_id} has no representable frame at {fps} FPS'
                )

            state = merge_continuity(scene_continuity, shot.continuity_patch)
            clips.append(
                EditorialClip(
                    scene_id=scene.scene_id,
                    shot_id=shot.shot_id,
                    scene_index=scene_index,
                    shot_index=shot_index,
                    start_frame=start,
                    end_frame=end,
                    duration_frames=end - start,
                    start_timecode=_timecode(start, fps),
                    end_timecode_exclusive=_timecode(end, fps),
                    continuity_changed_fields=_changed_fields(previous_state, state),
                    transition_in_declared=bool(shot.transition_in),
                    transition_out_declared=bool(shot.transition_out),
                )
            )
            previous_state = state

        declared = _seconds(scene.target_duration_seconds, f'scene {scene.scene_id}')
        scene_end_frame = _round_frames(cumulative, fps)
        actual_scene_frames = scene_end_frame - scene_start_frame
        desired_scene_frames = _round_frames(declared, fps)
        scene_delta = actual_scene_frames - desired_scene_frames
        scene_spans.append(
            EditorialSceneSpan(
                scene_id=scene.scene_id,
                scene_index=scene_index,
                start_frame=scene_start_frame,
                end_frame=scene_end_frame,
                duration_frames=actual_scene_frames,
                target_frames=desired_scene_frames,
                frame_difference=scene_delta,
                shot_count=len(scene.shots),
            )
        )
        if abs(scene_delta) > 1:
            warnings.append(f'Scene {scene.scene_id} duration differs from its shots')

    actual_frames = _round_frames(cumulative, fps)
    difference = actual_frames - target_frames
    if difference != 0:
        warnings.append(
            f'Shot timeline differs from project target by {difference} delivery frames'
        )
    return EditorialTimeline(
        project_id=project.id,
        project_revision=project.revision,
        delivery_fps=fps,
        target_frames=target_frames,
        actual_frames=actual_frames,
        frame_difference=difference,
        timecode_standard='integer-fps-non-drop',
        timeline_digest_sha256=_timeline_digest(
            project.id, project.revision, fps, target_frames, clips
        ),
        scenes=tuple(scene_spans),
        clips=tuple(clips),
        warnings=tuple(warnings),
    )
