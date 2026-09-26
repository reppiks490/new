from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field, model_validator


class InterpolationMode(str, Enum):
    LINEAR = "linear"
    STEP = "step"
    BEZIER = "bezier"


class Keyframe(BaseModel):
    time_seconds: float = Field(ge=0)
    value: tuple[float, ...]
    interpolation: InterpolationMode = InterpolationMode.BEZIER


class AnimationTrack(BaseModel):
    # A joint name (must match the target rig), or "morph:<name>" for a
    # blendshape/morph-target weight track rather than a skeletal joint.
    target_joint: str = Field(min_length=1)
    channel: str  # e.g. "translation", "rotation_quat", "scale", "weight"
    keyframes: list[Keyframe] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_monotonic_times(self):
        times = [k.time_seconds for k in self.keyframes]
        if times != sorted(times):
            raise ValueError(
                f"keyframe times for track {self.target_joint}/{self.channel} must be non-decreasing"
            )
        return self


class AnimationClip(BaseModel):
    name: str = Field(min_length=1)
    frame_rate: float = Field(gt=0, default=30.0)
    tracks: list[AnimationTrack] = Field(default_factory=list)
    loop: bool = False

    @property
    def duration_seconds(self) -> float:
        if not self.tracks:
            return 0.0
        return max(
            (k.time_seconds for t in self.tracks for k in t.keyframes),
            default=0.0,
        )
