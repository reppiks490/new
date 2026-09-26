from __future__ import annotations

"""Real local image -> structured-spec-hint analysis.

Scope note (do not remove): this is NOT a natural-language image captioner.
Producing "a photo of a woman in a red dress standing in a forest" from
pixels requires a trained vision-language model this environment does not
have and this project does not fabricate having (see docs/SECURITY_AND_TRUST.md
and this project's general execution-truth discipline). What this module
does instead is real, deterministic, local computation over the actual
pixels -- dominant palette, brightness/contrast, structural edge density,
and a resolution-driven texture-tier suggestion -- and returns them as
structured hints a caller can fold into a CharacterSpec/SceneSpec prompt or
material plan. That is a genuine (if modest) image-input bridge, not a
fabricated one.
"""

from pathlib import Path

import numpy as np
from PIL import Image
from pydantic import BaseModel, Field

from app.core.models import TextureTier


class DominantColor(BaseModel):
    rgb: tuple[int, int, int]
    proportion: float = Field(ge=0, le=1)


class ImagePromptHints(BaseModel):
    path: str
    width: int
    height: int
    megapixels: float
    dominant_colors: list[DominantColor]
    brightness_mean: float = Field(ge=0, le=255)
    contrast_std: float = Field(ge=0)
    edge_density: float = Field(ge=0)
    suggested_texture_tier: TextureTier
    warnings: list[str] = Field(default_factory=list)


def _edges(gray: np.ndarray) -> np.ndarray:
    # Same finite-difference edge proxy already used in
    # app/render/multiview.py::_edges -- reused rather than reinvented.
    gx = np.diff(gray, axis=1, append=gray[:, -1:])
    gy = np.diff(gray, axis=0, append=gray[-1:, :])
    return np.sqrt(gx * gx + gy * gy)


def _suggested_texture_tier(max_dimension: int) -> TextureTier:
    if max_dimension >= 8192:
        return TextureTier.T8K
    if max_dimension >= 4096:
        return TextureTier.T4K
    return TextureTier.T2K


def analyze_image_for_prompt(path: str | Path, *, palette_size: int = 5) -> ImagePromptHints:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    if not 1 <= palette_size <= 32:
        raise ValueError("palette_size must be between 1 and 32")

    with Image.open(path) as im:
        im = im.convert("RGB")
        width, height = im.size
        arr = np.asarray(im, dtype=np.float64)
        quantized = im.quantize(colors=palette_size)
        palette = quantized.getpalette() or []
        counts = quantized.getcolors() or []

    total_pixels = width * height
    dominant = []
    for count, idx in sorted(counts, reverse=True):
        r, g, b = palette[idx * 3: idx * 3 + 3]
        dominant.append(DominantColor(rgb=(r, g, b), proportion=round(count / total_pixels, 6)))

    gray = arr.mean(axis=2)
    brightness = float(gray.mean())
    contrast = float(gray.std())
    edge_density = float(_edges(gray).mean())

    warnings: list[str] = []
    if contrast < 5.0:
        warnings.append("Very low contrast; source image may be flat/blank and a poor generation reference.")
    if max(width, height) < 512:
        warnings.append("Source image is below 512px on its longest side; upscale or request a higher-resolution reference.")

    return ImagePromptHints(
        path=str(path),
        width=width,
        height=height,
        megapixels=round(total_pixels / 1_000_000, 4),
        dominant_colors=dominant,
        brightness_mean=round(brightness, 3),
        contrast_std=round(contrast, 3),
        edge_density=round(edge_density, 4),
        suggested_texture_tier=_suggested_texture_tier(max(width, height)),
        warnings=warnings,
    )
