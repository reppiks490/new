"""Read-only, provider-neutral capability preflight for long-form cinematic projects.

Compares persisted shot metadata to a *supplied* engine capability snapshot.
Never selects an engine, loads media, resolves local files, queues jobs or spends
money. A passing report does not prove runtime availability or playable output.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import TYPE_CHECKING

from app.video.cinematic_service import select_native_fps, select_native_resolution
from app.video.models import EngineCapabilities

if TYPE_CHECKING:
    from app.video.cinematic_models import CinematicProject

# The current VideoGenerationRequest has stricter requirements than some
# EngineCapabilities declarations. Validate both, not merely the advertisement.
_REQUEST_MIN_DURATION = 1.0
_REQUEST_MAX_DURATION = 30.0
_REQUEST_MAX_FPS = 60
_NATIVE_RESOLUTIONS = frozenset({"480p", "720p", "1080p"})


@dataclass(frozen=True)
class CapabilityFinding:
    severity: str
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
class CapabilityPreflight:
    project_id: str | None
    revision: int
    shot_count: int
    compatible_shots: int
    selected_native_fps: int | None
    selected_native_resolution: str | None
    findings: tuple[CapabilityFinding, ...]

    @property
    def capability_ready(self) -> bool:
        """Metadata compatibility only; no check of files, live GPU or FFmpeg."""
        return (
            self.shot_count > 0
            and self.compatible_shots == self.shot_count
            and not any(item.severity == "error" for item in self.findings)
        )

    def as_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "revision": self.revision,
            "shot_count": self.shot_count,
            "compatible_shots": self.compatible_shots,
            "capability_ready": self.capability_ready,
            "selected_native_fps": self.selected_native_fps,
            "selected_native_resolution": self.selected_native_resolution,
            "findings": [finding.as_dict() for finding in self.findings],
        }


def audit_engine_capabilities(
    project: CinematicProject, capabilities: EngineCapabilities
) -> CapabilityPreflight:
    """Check one explicitly chosen engine against every shot without side effects.

    Does not echo engine detail/name, camera strings, prompts, scene titles,
    continuity data, media paths or private URLs. Warnings report that the
    *requested delivery setting differs from native generation*, not that
    upscaling/interpolation is actually installed or has been performed.
    """
    findings: list[CapabilityFinding] = []

    def flag(
        severity: str, code: str,
        scene_id: str | None = None, shot_id: str | None = None,
    ) -> None:
        findings.append(CapabilityFinding(severity, code, scene_id, shot_id))

    if not capabilities.available:
        flag("error", "ENGINE_UNAVAILABLE")

    bounds = (capabilities.min_duration_seconds, capabilities.max_duration_seconds)
    # A provider capability snapshot is normally Pydantic-validated, but
    # model_copy(update=...) and adapter code can bypass that validation.
    # Report malformed declarations neutrally rather than crashing preflight.
    valid_bounds = (
        all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and value > 0
            for value in bounds
        )
        and bounds[0] <= bounds[1]
    )
    if not valid_bounds:
        flag("error", "ENGINE_DURATION_DECLARATION_INVALID")

    native_fps: int | None = None
    if not capabilities.supported_fps or any(
        not isinstance(v, int) or isinstance(v, bool) or v < 1
        for v in capabilities.supported_fps
    ):
        flag("error", "ENGINE_FPS_DECLARATION_INVALID")
    else:
        native_fps = select_native_fps(
            project.delivery_fps, capabilities.supported_fps
        )
        if native_fps > _REQUEST_MAX_FPS:
            flag("error", "NATIVE_FPS_EXCEEDS_REQUEST_MODEL")
        elif native_fps != project.delivery_fps:
            flag(
                "warning",
                "DELIVERY_FPS_REQUIRES_FINISHING"
                if native_fps < project.delivery_fps
                else "NATIVE_FPS_ABOVE_DELIVERY",
            )

    native_resolution: str | None = None
    if not isinstance(capabilities.supported_resolutions, (list, tuple)) or not capabilities.supported_resolutions or any(
        not isinstance(item, str) or item not in _NATIVE_RESOLUTIONS
        for item in capabilities.supported_resolutions
    ):
        flag("error", "ENGINE_RESOLUTION_DECLARATION_INVALID")
    else:
        native_resolution = select_native_resolution(
            project.delivery_resolution, list(capabilities.supported_resolutions)
        )
        resolutions = {"480p": 480, "720p": 720, "1080p": 1080, "1440p": 1440, "2160p": 2160}
        if native_resolution != project.delivery_resolution:
            flag(
                "warning",
                "DELIVERY_RESOLUTION_REQUIRES_FINISHING"
                if resolutions[native_resolution] < resolutions[project.delivery_resolution]
                else "NATIVE_RESOLUTION_ABOVE_DELIVERY",
            )

    global_errors = any(item.severity == "error" for item in findings)
    shot_count = 0
    compatible_count = 0

    for scene in project.scenes:
        for shot in scene.shots:
            shot_count += 1
            before = len(findings)

            if shot.engine_profile not in capabilities.profiles:
                flag("error", "SHOT_PROFILE_UNSUPPORTED", scene.scene_id, shot.shot_id)
            if (
                not valid_bounds
                or shot.duration_seconds < max(_REQUEST_MIN_DURATION, bounds[0])
                or shot.duration_seconds > min(_REQUEST_MAX_DURATION, bounds[1])
            ):
                flag("error", "SHOT_DURATION_UNSUPPORTED", scene.scene_id, shot.shot_id)
            if shot.motion_strength is not None and not capabilities.supports_motion_strength:
                flag("error", "SHOT_MOTION_STRENGTH_UNSUPPORTED", scene.scene_id, shot.shot_id)
            if (
                shot.camera_motion is not None
                and shot.camera_motion not in capabilities.camera_motion_presets
            ):
                flag("error", "SHOT_CAMERA_MOTION_UNSUPPORTED", scene.scene_id, shot.shot_id)

            # This request type carries just one source image. The render
            # service picks the first inherited reference; all others are not
            # consumed as image inputs by VideoGenerationRequest.
            ordered_references = tuple(dict.fromkeys((
                *project.reference_image_ids,
                *scene.reference_image_ids,
                *shot.reference_image_ids,
            )))
            if len(ordered_references) > 1:
                flag("warning", "ADDITIONAL_REFERENCES_NOT_IMAGE_INPUTS", scene.scene_id, shot.shot_id)
            if (
                shot.reference_image_ids
                and ordered_references
                and ordered_references[0] not in shot.reference_image_ids
            ):
                flag("warning", "SHOT_REFERENCE_NOT_PRIMARY_SOURCE", scene.scene_id, shot.shot_id)

            # Persisted editorial intent may be useful to later finishing
            # stages, but these fields are not accepted by the current
            # VideoGenerationRequest and do not control shot generation.
            if shot.lens_mm is not None:
                flag("warning", "LENS_CONTROL_NOT_FORWARDED", scene.scene_id, shot.shot_id)
            if shot.framing is not None:
                flag("warning", "FRAMING_NOT_FORWARDED", scene.scene_id, shot.shot_id)
            if shot.transition_in is not None or shot.transition_out is not None:
                flag("warning", "TRANSITION_NOT_SHOT_GENERATION", scene.scene_id, shot.shot_id)

            # Warnings describe missing/finishing-stage creative capabilities,
            # not a failure to send a legal request to the declared engine.
            if not global_errors and not any(
                finding.severity == "error" for finding in findings[before:]
            ):
                compatible_count += 1

    return CapabilityPreflight(
        project_id=project.id,
        revision=project.revision,
        shot_count=shot_count,
        compatible_shots=compatible_count,
        selected_native_fps=native_fps,
        selected_native_resolution=native_resolution,
        findings=tuple(findings),
    )
