"""Frame-accurate, side-effect-free editorial preflight for cinematic projects.

This module prepares an edit decision list (EDL), not a rendered master. It
never reads media, exposes prompt text, or guesses whether a shot was rendered.
The project sequence is authoritative; ordinal fields are diagnostic only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
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
    continuity_changed_fields: tuple[str, ...]
    transition_in: str | None
    transition_out: str | None


@dataclass(frozen=True)
class EditorialTimeline:
    project_id: str
    project_revision: int
    delivery_fps: int
    target_frames: int
    actual_frames: int
    frame_difference: int
    clips: tuple[EditorialClip, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible snapshot containing identifiers, not prompts."""
        return asdict(self)


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
    if not isinstance(fps, int) or isinstance(fps, bool) or fps <= 0:
        raise TimelineValidationError('delivery_fps must be a positive integer')
    if not project.id:
        raise TimelineValidationError('project must have a persisted identifier')

    target_frames = _round_frames(
        _seconds(project.target_duration_seconds, 'project'), fps
    )
    warnings: list[str] = []
    clips: list[EditorialClip] = []
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

            state = merge_continuity(
                merge_continuity(project.continuity_bible, scene.continuity_patch),
                shot.continuity_patch,
            )
            clips.append(
                EditorialClip(
                    scene_id=scene.scene_id,
                    shot_id=shot.shot_id,
                    scene_index=scene_index,
                    shot_index=shot_index,
                    start_frame=start,
                    end_frame=end,
                    duration_frames=end - start,
                    continuity_changed_fields=_changed_fields(previous_state, state),
                    transition_in=shot.transition_in,
                    transition_out=shot.transition_out,
                )
            )
            previous_state = state

        if scene.shots:
            declared = _seconds(scene.target_duration_seconds, f'scene {scene.scene_id}')
            if abs(_round_frames(declared - scene_total, fps)) > 1:
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
        clips=tuple(clips),
        warnings=tuple(warnings),
    )
