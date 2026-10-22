"""Opt-in, read-only inspection of a cinematic project's private reference PNGs.

Unlike metadata-only readiness, this verifier reads existing local image files.
Call it only on a trusted local workspace. It neither creates directories nor
loads generation models, and does not publish image paths, pixels or fingerprints.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import TYPE_CHECKING

from PIL import Image, UnidentifiedImageError

if TYPE_CHECKING:
    from app.video.cinematic_models import CinematicProject

_ID = re.compile(r"^[a-f0-9]{32}$")
# Align with the image uploader's 20 MP source-image boundary.
_MAX_PIXELS = 20_000_000
_MAX_BYTES = 12 * 1024 * 1024


@dataclass(frozen=True)
class ReferenceFinding:
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
class ReferenceFilePreflight:
    project_id: str | None
    revision: int
    shot_count: int
    shots_with_valid_references: int
    unique_references: int
    valid_unique_references: int
    findings: tuple[ReferenceFinding, ...]

    @property
    def references_ready(self) -> bool:
        """File snapshot only, not permission for generation or asset immutability."""
        return (
            self.shot_count > 0
            and self.shots_with_valid_references == self.shot_count
            and self.unique_references == self.valid_unique_references
            and not any(f.severity == "error" for f in self.findings)
        )

    def as_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "revision": self.revision,
            "shot_count": self.shot_count,
            "shots_with_valid_references": self.shots_with_valid_references,
            "unique_references": self.unique_references,
            "valid_unique_references": self.valid_unique_references,
            "references_ready": self.references_ready,
            "findings": [f.as_dict() for f in self.findings],
        }


def _reference_status(directory: Path, identifier: str) -> str | None:
    """Return a neutral error code, or None for an actually decodable PNG."""
    if not isinstance(identifier, str) or _ID.fullmatch(identifier) is None:
        return "REFERENCE_ID_INVALID"
    path = directory / (identifier + ".png")
    try:
        # Check the normalized file path; never resolve user-provided relative paths.
        if path.is_symlink() or not path.resolve().is_relative_to(directory):
            return "REFERENCE_PATH_UNSAFE"
        if not path.is_file():
            return "REFERENCE_FILE_MISSING"
        # Keep local inspection within the same byte limit as image uploads,
        # before attempting a potentially expensive decode.
        if path.stat().st_size > _MAX_BYTES:
            return "REFERENCE_TOO_MANY_BYTES"
        with Image.open(path) as image:
            if image.format != "PNG":
                return "REFERENCE_FORMAT_INVALID"
            if image.width * image.height > _MAX_PIXELS:
                return "REFERENCE_TOO_MANY_PIXELS"
            image.verify()
        # verify() examines container integrity; load() also catches truncated
        # image data in the source pixel stream.
        with Image.open(path) as image:
            image.load()
    except PermissionError:
        return "REFERENCE_FILE_UNREADABLE"
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        return "REFERENCE_TOO_MANY_PIXELS"
    except (OSError, ValueError, UnidentifiedImageError):
        return "REFERENCE_IMAGE_INVALID"
    return None


def audit_reference_files(project: CinematicProject, *, workspace: Path) -> ReferenceFilePreflight:
    """Inspect every distinct inherited reference exactly once and map failures to shots.

    The source IDs are supplied by validated project models; an extra ID guard
    protects against unsafe model_copy()/in-memory edits. Per-shot failures are
    intentionally repeated to make large production timelines actionable.
    Never call this as a substitute for the service's render-time asset checks:
    files may change between verification and use.
    """
    findings: list[ReferenceFinding] = []

    def flag(code: str, scene_id: str | None = None, shot_id: str | None = None) -> None:
        findings.append(ReferenceFinding("error", code, scene_id, shot_id))

    shots: list[tuple[str, str, tuple[str, ...]]] = []
    for scene in project.scenes:
        for shot in scene.shots:
            identifiers = tuple(dict.fromkeys((
                *project.reference_image_ids,
                *scene.reference_image_ids,
                *shot.reference_image_ids,
            )))
            shots.append((scene.scene_id, shot.shot_id, identifiers))
    all_ids = tuple(dict.fromkeys(ref for _, _, refs in shots for ref in refs))

    if not shots:
        flag("NO_SHOTS")

    workspace = Path(workspace)
    directory = workspace / "video-assets"
    workspace_ok = False
    try:
        # No mkdir: inspecting a nonexistent or unsafe workspace must not mutate it.
        if workspace.is_symlink() or not workspace.is_dir():
            flag("WORKSPACE_UNAVAILABLE")
        elif directory.is_symlink() or not directory.is_dir():
            flag("REFERENCE_DIRECTORY_UNAVAILABLE")
        elif not directory.resolve().is_relative_to(workspace.resolve()):
            flag("REFERENCE_DIRECTORY_UNSAFE")
        else:
            workspace_ok = True
    except (OSError, ValueError):
        flag("WORKSPACE_UNAVAILABLE")

    statuses: dict[str, str | None] = {}
    if workspace_ok:
        for identifier in all_ids:
            statuses[identifier] = _reference_status(directory.resolve(), identifier)

    valid_shots = 0
    for scene_id, shot_id, references in shots:
        if not references:
            flag("NO_SOURCE_REFERENCE", scene_id, shot_id)
            continue
        if not workspace_ok:
            continue
        failed = False
        for identifier in references:
            error_code = statuses[identifier]
            if error_code is not None:
                flag(error_code, scene_id, shot_id)
                failed = True
        if not failed:
            valid_shots += 1

    return ReferenceFilePreflight(
        project_id=project.id,
        revision=project.revision,
        shot_count=len(shots),
        shots_with_valid_references=valid_shots,
        unique_references=len(all_ids),
        valid_unique_references=sum(error is None for error in statuses.values()),
        findings=tuple(findings),
    )
