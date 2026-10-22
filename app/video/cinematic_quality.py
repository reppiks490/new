"""Deterministic, privacy-preserving preflight checks for cinematic timelines.

This layer audits *metadata only*. It never opens private media, calls a render
engine, or claims that an engine or an image asset is available.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from app.video.cinematic_models import CinematicProject

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class TimelineFinding:
    severity: Severity
    code: str
    scene_id: str | None = None
    shot_id: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "severity": self.severity,
            "code": self.code,
            "scene_id": self.scene_id,
            "shot_id": self.shot_id,
        }


@dataclass(frozen=True)
class TimelinePreflight:
    project_id: str | None
    revision: int
    scene_count: int
    shot_count: int
    target_seconds: float
    planned_seconds: float
    source_reference_shots: int
    findings: tuple[TimelineFinding, ...]

    @property
    def structurally_ready(self) -> bool:
        """Means no metadata errors; NOT proof of assets, engine, or output quality."""
        return not any(item.severity == "error" for item in self.findings)

    def as_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "revision": self.revision,
            "scene_count": self.scene_count,
            "shot_count": self.shot_count,
            "target_seconds": self.target_seconds,
            "planned_seconds": self.planned_seconds,
            "source_reference_shots": self.source_reference_shots,
            "structurally_ready": self.structurally_ready,
            "findings": [item.as_dict() for item in self.findings],
        }


def _seconds(number: float) -> Decimal:
    return Decimal(str(number))


def audit_timeline(
    project: CinematicProject, *, tolerance_seconds: float = 0.001
) -> TimelinePreflight:
    """Audit ordering, edit budgets, inherited sources, and immutable continuity.

    Findings contain codes/opaque IDs only: never titles, prompts, scene text,
    continuity values, media paths, or private URLs. No input is mutated.
    The caller must separately validate actual source assets and engine support.
    """
    if not (0 <= tolerance_seconds < float("inf")):
        raise ValueError("tolerance_seconds must be finite and non-negative")
    tolerance = _seconds(tolerance_seconds)
    findings: list[TimelineFinding] = []

    def flag(
        severity: Severity, code: str, scene_id: str | None = None,
        shot_id: str | None = None,
    ) -> None:
        findings.append(TimelineFinding(severity, code, scene_id, shot_id))

    if not project.scenes:
        flag("error", "NO_SCENES")

    planned = Decimal(0)
    shot_count = 0
    source_count = 0

    for scene_number, scene in enumerate(project.scenes, start=1):
        if scene.ordinal != scene_number:
            flag("warning", "SCENE_ORDER_MISMATCH", scene.scene_id)

        scene_planned = Decimal(0)
        if not scene.shots:
            flag("error", "EMPTY_SCENE", scene.scene_id)

        scene_immutable = scene.continuity_patch.immutable_constraints
        project_immutable = project.continuity_bible.immutable_constraints
        if (
            scene_immutable is not None
            and project_immutable is not None
            and scene_immutable != project_immutable
        ):
            flag("error", "IMMUTABLE_CONTINUITY_OVERRIDE", scene.scene_id)

        previous_ordinal = 0
        for shot in scene.shots:
            shot_count += 1
            scene_planned += _seconds(shot.duration_seconds)
            if shot.ordinal <= previous_ordinal:
                flag("warning", "SHOT_ORDER_MISMATCH", scene.scene_id, shot.shot_id)
            previous_ordinal = shot.ordinal

            has_source = bool(
                project.reference_image_ids
                or scene.reference_image_ids
                or shot.reference_image_ids
            )
            if has_source:
                source_count += 1
            else:
                flag("error", "NO_SOURCE_REFERENCE", scene.scene_id, shot.shot_id)

            shot_immutable = shot.continuity_patch.immutable_constraints
            effective_parent = (
                scene_immutable if scene_immutable is not None else project_immutable
            )
            if (
                shot_immutable is not None
                and effective_parent is not None
                and shot_immutable != effective_parent
            ):
                flag(
                    "error", "IMMUTABLE_CONTINUITY_OVERRIDE",
                    scene.scene_id, shot.shot_id,
                )

        planned += scene_planned
        if abs(scene_planned - _seconds(scene.target_duration_seconds)) > tolerance:
            flag("error", "SCENE_DURATION_MISMATCH", scene.scene_id)

    if abs(planned - _seconds(project.target_duration_seconds)) > tolerance:
        flag("error", "PROJECT_DURATION_MISMATCH")

    return TimelinePreflight(
        project_id=project.id,
        revision=project.revision,
        scene_count=len(project.scenes),
        shot_count=shot_count,
        target_seconds=project.target_duration_seconds,
        planned_seconds=float(planned),
        source_reference_shots=source_count,
        findings=tuple(findings),
    )
