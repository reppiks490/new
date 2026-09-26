from __future__ import annotations
from pydantic import BaseModel, Field
from app.core.animation_models import AnimationClip

class AnimationQAReport(BaseModel):
    track_count: int
    duration_seconds: float
    unknown_joint_count: int
    empty_track_count: int
    passed: bool
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

def qa_animation_clip(clip: AnimationClip, *, known_joints: set[str] | None = None) -> AnimationQAReport:
    blockers: list[str] = []; warnings: list[str] = []
    empty = sum(1 for t in clip.tracks if not t.keyframes)
    unknown = 0
    if known_joints:
        for t in clip.tracks:
            if not t.target_joint.startswith("morph:") and t.target_joint not in known_joints:
                unknown += 1
    if empty: blockers.append(f'{empty} animation track(s) have no keyframes.')
    if unknown: blockers.append(f'{unknown} track(s) target joints not present in the bound rig.')
    if not clip.tracks: warnings.append('Animation clip has no tracks.')
    return AnimationQAReport(
        track_count=len(clip.tracks),
        duration_seconds=clip.duration_seconds,
        unknown_joint_count=unknown,
        empty_track_count=empty,
        passed=not blockers,
        blockers=blockers,
        warnings=warnings,
    )
