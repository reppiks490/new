from __future__ import annotations

from pathlib import Path
from pydantic import BaseModel, Field

from app.qa.groom_collision import GroomCollisionReport, qa_groom_collisions


class GroomFrameSample(BaseModel):
    frame: int
    strands: list[list[list[float]]]


class GroomFrameResult(BaseModel):
    frame: int
    collision_ratio: float
    penetration_point_count: int
    minimum_clearance: float
    passed: bool


class AnimatedGroomCollisionReport(BaseModel):
    frame_count: int
    failed_frames: list[int]
    worst_collision_ratio: float = Field(ge=0, le=1)
    minimum_clearance: float
    passed: bool
    frames: list[GroomFrameResult]
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def qa_animated_groom_collisions(
    body_mesh: str | Path,
    samples: list[GroomFrameSample],
    *,
    sample_stride: int = 2,
    allowed_penetration_ratio: float = 0.002,
) -> AnimatedGroomCollisionReport:
    if not samples:
        return AnimatedGroomCollisionReport(
            frame_count=0,
            failed_frames=[],
            worst_collision_ratio=0,
            minimum_clearance=float("inf"),
            passed=True,
            frames=[],
            warnings=["No animated groom frames were supplied."],
        )
    results: list[GroomFrameResult] = []
    blockers: list[str] = []
    warnings: list[str] = []
    for sample in sorted(samples, key=lambda x: x.frame):
        report: GroomCollisionReport = qa_groom_collisions(
            body_mesh,
            sample.strands,
            sample_stride=sample_stride,
            allowed_penetration_ratio=allowed_penetration_ratio,
        )
        results.append(
            GroomFrameResult(
                frame=sample.frame,
                collision_ratio=report.collision_ratio,
                penetration_point_count=report.penetration_point_count,
                minimum_clearance=report.minimum_clearance,
                passed=report.passed,
            )
        )
        warnings.extend(f"frame {sample.frame}: {w}" for w in report.warnings)
        if not report.passed:
            blockers.extend(f"frame {sample.frame}: {b}" for b in report.blockers)
    failed = [r.frame for r in results if not r.passed]
    return AnimatedGroomCollisionReport(
        frame_count=len(results),
        failed_frames=failed,
        worst_collision_ratio=max(r.collision_ratio for r in results),
        minimum_clearance=min(r.minimum_clearance for r in results),
        passed=not failed,
        frames=results,
        blockers=blockers,
        warnings=warnings,
    )
