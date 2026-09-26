from __future__ import annotations

"""Hi3D specialty-mode request builders (portrait, relief, multicolor,
print-split), extending app/providers/hi3d.py's generic image_task_fields.

Confidence note (do not remove): web search this session (direct fetch to
docs.hi3d.ai is blocked by this environment's egress policy -- confirmed,
not assumed) corroborated that Hi3D documents a Portrait model tuned for
human busts/figures, a Depth-Map/relief mode producing an EXR/PNG relief
rather than a full mesh, a Multicolor Mesh mode with a "number of colors"
parameter commonly paired with 3MF output, and a Character Split mode with
part/joint parameters. It did NOT surface the raw submit-task endpoint's
exact wire field names for selecting these modes. This module therefore:
  (a) reuses the shipped, already-integrated image_task_fields fields
      (model, format, face, resolution, pbr, rmbg, shading, request_type)
      wherever this session found no reason to doubt them, and
  (b) adds mode-specific fields using Hi3D's own documented terminology,
      explicitly marked as best-effort / unconfirmed against the live wire
      format, per this project's own execution-truth discipline
      (docs/V10_EXECUTION_TRUTH.md): treat any task submitted through these
      builders as SYNTHETIC/COMPILED_ONLY, not LIVE, until validated against
      a real Hi3D account and corrected here if wrong.
"""

from enum import Enum

from app.providers.hi3d import high_density_submission_plan, image_task_fields


class Hi3DMode(str, Enum):
    STANDARD = "standard"
    PORTRAIT = "portrait"
    RELIEF = "relief"
    MULTICOLOR = "multicolor"
    PRINT_SPLIT = "print_split"


_RELIEF_FORMATS = {"exr", "png"}


def portrait_task_fields(*, face_count: int = 2_000_000, pbr: bool = True, output_format: str = "glb", callback_url: str | None = None) -> dict:
    """Portrait/bust/figure-specialized reconstruction. Reuses the standard
    image_task_fields shape; the model identifier below is best-effort
    (unconfirmed wire value -- see module docstring)."""
    fields = image_task_fields(face_count=face_count, pbr=pbr, output_format=output_format, callback_url=callback_url, model="hi3d-portrait")
    fields["mode"] = Hi3DMode.PORTRAIT.value
    return fields


def relief_task_fields(*, output_format: str = "exr", callback_url: str | None = None) -> dict:
    """Depth-map/relief generation: output is a height/relief map, not a
    full 3D mesh, so this does NOT reuse image_task_fields' mesh format_map
    or face-count submission ladder (a relief map has no face count)."""
    if output_format not in _RELIEF_FORMATS:
        raise ValueError(f"Hi3D relief output_format must be one of {sorted(_RELIEF_FORMATS)}")
    fields = {
        "request_type": "relief",  # best-effort; unconfirmed wire value
        "mode": Hi3DMode.RELIEF.value,
        "model": "hi3d-relief",
        "format": output_format,
    }
    if callback_url:
        fields["callback_url"] = callback_url
    return fields


def multicolor_task_fields(*, number_colors: int = 4, face_count: int = 2_000_000, callback_url: str | None = None) -> dict:
    """Multicolor mesh preparation for print, per documented "number of
    colors" parameter, commonly paired with 3MF export."""
    if not 2 <= number_colors <= 16:
        raise ValueError("Hi3D multicolor number_colors must be between 2 and 16")
    fields = image_task_fields(face_count=face_count, output_format="3mf", callback_url=callback_url, model="hi3d-multicolor")
    fields["mode"] = Hi3DMode.MULTICOLOR.value
    fields["number_color"] = str(number_colors)
    return fields


def print_split_task_fields(*, part_count: int = 2, joint_style: str = "dovetail", face_count: int = 2_000_000, callback_url: str | None = None) -> dict:
    """3D-print model splitting: cut a dense mesh into printable parts with
    the documented part/joint parameters."""
    if part_count < 2:
        raise ValueError("Hi3D print-split part_count must be >= 2")
    fields = image_task_fields(face_count=face_count, output_format="3mf", callback_url=callback_url, model="hi3d-split")
    fields["mode"] = Hi3DMode.PRINT_SPLIT.value
    fields["part"] = str(part_count)
    fields["joint"] = joint_style
    return fields
