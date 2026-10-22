"""Unified, deterministic cinematic preflight dossier for a trusted local caller.

Aggregates three independently tested checks without acquiring rendering
authority. No background work, queues, media writes, secrets, or GPU calls.
Missing checks remain explicitly NOT_CHECKED, never silently green.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from app.video.cinematic_capability_preflight import audit_engine_capabilities
from app.video.cinematic_quality import audit_timeline
from app.video.cinematic_reference_preflight import audit_reference_files
from app.video.models import EngineCapabilities

if TYPE_CHECKING:
    from app.video.cinematic_models import CinematicProject

StageStatus = Literal["passed", "blocked", "not_checked"]

_STAGES = ("timeline", "engine_capability", "reference_files")


@dataclass(frozen=True)
class ReadinessStage:
    name: str
    status: StageStatus
    errors: int
    warnings: int
    detail: dict | None = None

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "errors": self.errors,
            "warnings": self.warnings,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ProjectPreflightDossier:
    project_id: str | None
    revision: int
    shot_count: int
    completed_stages: int
    total_stages: int
    stages: tuple[ReadinessStage, ...]

    @property
    def preflight_complete(self) -> bool:
        return self.completed_stages == self.total_stages

    @property
    def preflight_passed(self) -> bool:
        """Not permission to render, proof of media, or an engine health guarantee."""
        return self.preflight_complete and all(
            stage.status == "passed" for stage in self.stages
        )

    @property
    def blockers(self) -> int:
        return sum(stage.errors for stage in self.stages)

    def as_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "revision": self.revision,
            "shot_count": self.shot_count,
            "completed_stages": self.completed_stages,
            "total_stages": self.total_stages,
            "preflight_complete": self.preflight_complete,
            "preflight_passed": self.preflight_passed,
            "blockers": self.blockers,
            "stages": [stage.as_dict() for stage in self.stages],
        }


def _stage(
    name: str,
    *,
    passed: bool | None,
    details: dict | None = None,
) -> ReadinessStage:
    if passed is None:
        return ReadinessStage(name, "not_checked", 0, 0)
    findings = details["findings"] if details is not None else []
    return ReadinessStage(
        name=name,
        status="passed" if passed else "blocked",
        errors=sum(f["severity"] == "error" for f in findings),
        warnings=sum(f["severity"] == "warning" for f in findings),
        detail=details,
    )


def audit_project_preflight(
    project: CinematicProject,
    *,
    capabilities: EngineCapabilities | None = None,
    trusted_workspace: Path | None = None,
) -> ProjectPreflightDossier:
    """Produce a neutral cross-stage report; fail closed on omitted checks.

    capabilities must describe the specifically selected candidate engine.
    trusted_workspace must be chosen by trusted server code, not from a
    remote client query. Without either, its stage is "not_checked"; none of
    the optional checks are invoked. The timeline stage always runs.

    Even when all three stages pass, render-time source checks, permissions,
    cache provenance, hardware readiness, FFmpeg verification and phone
    playback must be checked separately.
    """
    timeline = audit_timeline(project)
    stages = [
        _stage(
            "timeline",
            passed=timeline.structurally_ready,
            details=timeline.as_dict(),
        )
    ]

    if capabilities is None:
        stages.append(_stage("engine_capability", passed=None))
    else:
        engine = audit_engine_capabilities(project, capabilities)
        stages.append(_stage(
            "engine_capability",
            passed=engine.capability_ready,
            details=engine.as_dict(),
        ))

    if trusted_workspace is None:
        stages.append(_stage("reference_files", passed=None))
    else:
        references = audit_reference_files(project, workspace=trusted_workspace)
        stages.append(_stage(
            "reference_files",
            passed=references.references_ready,
            details=references.as_dict(),
        ))

    assert tuple(stage.name for stage in stages) == _STAGES
    return ProjectPreflightDossier(
        project_id=project.id,
        revision=project.revision,
        shot_count=timeline.shot_count,
        completed_stages=sum(stage.status != "not_checked" for stage in stages),
        total_stages=len(stages),
        stages=tuple(stages),
    )
