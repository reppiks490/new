from __future__ import annotations

from pathlib import Path
from PIL import Image
from pydantic import BaseModel, Field

# PIL's default decompression-bomb guard (Image.MAX_IMAGE_PIXELS, ~89.5M
# pixels) exists to protect against maliciously crafted images from
# untrusted sources. Files this function inspects come from this project's
# own bake/render pipeline (app/qa/bake_output_verification.py,
# app/render/output_verification.py), not arbitrary uploads, and this
# project's own largest outputs are the 16K render tier (15360x8640 =
# 132,710,400 px -- app/render/output_resolution.py) and 16K square biome
# textures (16384x16384 = 268,435,456 px --
# app/world/biome_texture_synthesis.py::MAX_TEXTURE_SIZE).
# Rather than disable the guard entirely, raise it to a fixed, still-bounded
# cap above that known ceiling, so a genuinely oversized/hostile file is
# still rejected.
Image.MAX_IMAGE_PIXELS = 300_000_000


class TextureQAReport(BaseModel):
    path: str
    width: int
    height: int
    mode: str
    format: str | None
    megapixels: float
    max_dimension: int
    meets_2k: bool
    meets_4k: bool
    meets_8k: bool
    warnings: list[str] = Field(default_factory=list)


def inspect_texture(path: str | Path) -> TextureQAReport:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    with Image.open(path) as im:
        width, height = im.size
        mode = im.mode
        fmt = im.format
    max_dim = max(width, height)
    warnings: list[str] = []
    if width != height:
        warnings.append("Texture is non-square; valid for some maps, but verify expected UV/UDIM layout.")
    if max_dim < 2048:
        warnings.append("Texture is below the 2K production floor.")
    return TextureQAReport(
        path=str(path), width=width, height=height, mode=mode, format=fmt,
        megapixels=round(width * height / 1_000_000, 4), max_dimension=max_dim,
        meets_2k=max_dim >= 2048, meets_4k=max_dim >= 4096, meets_8k=max_dim >= 8192,
        warnings=warnings,
    )
