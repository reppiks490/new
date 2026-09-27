from __future__ import annotations

import struct
from pathlib import Path

from pydantic import BaseModel, Field

from app.providers.provenance import sha256_file
from app.qa.textures import inspect_texture
from app.render.output_resolution import RenderOutputSpec


EXR_MAGIC = 20000630


def exr_dimensions(path: str | Path) -> tuple[int, int]:
    """Width/height of a scanline or tiled OpenEXR from its header's
    required `dataWindow` (box2i: xMin, yMin, xMax, yMax, inclusive). PIL
    cannot read EXR, which is the hero/extreme render format."""
    with open(path, "rb") as f:
        head = f.read(8)
        if len(head) < 8 or struct.unpack("<i", head[:4])[0] != EXR_MAGIC:
            raise ValueError("not an OpenEXR file")
        if struct.unpack("<I", head[4:8])[0] & 0x1000:
            raise ValueError("multi-part OpenEXR is not supported by this reader")
        while True:
            name = b""
            while (c := f.read(1)) not in (b"\0", b""):
                name += c
            if not name:
                raise ValueError("OpenEXR header has no dataWindow attribute")
            while f.read(1) not in (b"\0", b""):
                pass
            size = struct.unpack("<i", f.read(4))[0]
            value = f.read(size)
            if name == b"dataWindow":
                x0, y0, x1, y1 = struct.unpack("<4i", value)
                return x1 - x0 + 1, y1 - y0 + 1


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
            with open(p, "rb") as fh:
                magic = fh.read(4)
            if magic == struct.pack("<i", EXR_MAGIC):
                width, height = exr_dimensions(p)
            else:
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
