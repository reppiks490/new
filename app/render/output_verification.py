from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from app.providers.provenance import sha256_file
from app.qa.textures import inspect_texture
from app.render.output_resolution import RenderOutputSpec


class RenderOutputVerification(BaseModel):
    path: str
    exists: bool
    width: int | None = None
    height: int | None = None
    meets_or_exceeds_spec: bool = False
    non_empty: bool = False
    sha256: str | None = None
    blockers: list[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.exists and self.non_empty and self.meets_or_exceeds_spec and not self.blockers


def verify_render_output(spec: RenderOutputSpec, path: str | Path) -> RenderOutputVerification:
    """Actually open a rendered output file and confirm its real dimensions
    meet or exceed the requested RenderOutputSpec (including overscan), the
    same discipline as app/qa/bake_output_verification.py: a render job
    "succeeding" is not itself proof the output file is the resolution it
    was supposed to be -- this opens the file and checks, using the
    already-real app/qa/textures.py::inspect_texture rather than
    reinventing image inspection, and hashes it via the already-real
    app/providers/provenance.py::sha256_file.
    """
    p = Path(path)
    if not p.is_file():
        return RenderOutputVerification(path=str(p), exists=False, blockers=[f"{p} does not exist."])

    size = p.stat().st_size
    non_empty = size > 0
    blockers: list[str] = []
    width = height = None
    meets = False

    if not non_empty:
        blockers.append("File exists but is zero bytes.")
    else:
        try:
            texture_report = inspect_texture(p)
            width, height = texture_report.width, texture_report.height
            meets = width >= spec.full_width and height >= spec.full_height
            if not meets:
                blockers.append(
                    f"Rendered output {width}x{height} is below the required "
                    f"{spec.full_width}x{spec.full_height} (including {spec.overscan_px}px overscan)."
                )
        except Exception as exc:
            blockers.append(f"Could not read rendered image: {exc}")

    digest = sha256_file(p) if non_empty else None
    return RenderOutputVerification(
        path=str(p), exists=True, width=width, height=height,
        meets_or_exceeds_spec=meets, non_empty=non_empty, sha256=digest, blockers=blockers,
    )
