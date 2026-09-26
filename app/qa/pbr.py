from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import numpy as np
from PIL import Image
from pydantic import BaseModel, Field

MapKind = Literal['basecolor','normal','roughness','metallic','ao','height','displacement','sss','opacity','unknown']

_PATTERNS = {
    'basecolor': ('basecolor','base_color','albedo','diffuse','color'),
    'normal': ('normal','nrm','nor'),
    'roughness': ('roughness','rough'),
    'metallic': ('metallic','metalness','metal'),
    'ao': ('ambientocclusion','ambient_occlusion','occlusion','ao'),
    'height': ('height',),
    'displacement': ('displacement','disp'),
    'sss': ('subsurface','sss'),
    'opacity': ('opacity','alpha'),
}

class PBRMapReport(BaseModel):
    path: str
    kind: MapKind
    width: int
    height: int
    channels: int
    bit_depth: int
    expected_color_space: str
    inferred_udim: int | None = None
    finite_ratio: float = Field(ge=0, le=1)
    dynamic_range: float = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)


def infer_map_kind(path: str | Path) -> MapKind:
    stem = Path(path).stem.lower()
    tokens = set(filter(None, re.split(r'[^a-z0-9]+', stem)))
    collapsed = ''.join(tokens)
    for kind, aliases in _PATTERNS.items():
        if any(alias in tokens or alias in collapsed for alias in aliases):
            return kind  # type: ignore[return-value]
    return 'unknown'


def _udim(path: Path) -> int | None:
    hits = re.findall(r'(?<!\d)(1\d{3})(?!\d)', path.stem)
    for h in reversed(hits):
        n = int(h)
        if 1001 <= n <= 1999:
            return n
    return None


def inspect_pbr_map(path: str | Path, kind: MapKind | None = None) -> PBRMapReport:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    kind = kind or infer_map_kind(path)
    with Image.open(path) as im:
        width, height = im.size
        arr = np.asarray(im)
        mode = im.mode
    channels = 1 if arr.ndim == 2 else int(arr.shape[-1])
    bit_depth = 16 if '16' in mode or arr.dtype.itemsize >= 2 else 8
    finite = np.isfinite(arr.astype(np.float64, copy=False))
    finite_ratio = float(np.count_nonzero(finite) / max(finite.size, 1))
    dynamic = float(np.nanmax(arr) - np.nanmin(arr)) if arr.size else 0.0
    data_maps = {'normal','roughness','metallic','ao','height','displacement','sss','opacity'}
    expected = 'Non-Color' if kind in data_maps else 'sRGB'
    warnings: list[str] = []
    if kind == 'unknown':
        warnings.append('Could not infer PBR semantic from filename; require explicit map role before shading.')
    if kind in {'height','displacement'} and bit_depth < 16:
        warnings.append('Height/displacement is below 16-bit; banding risk is elevated for hero-quality displacement.')
    if kind in {'roughness','metallic','ao','height','displacement','sss','opacity'} and channels > 1:
        warnings.append('Scalar data map has multiple channels; verify channel packing before import.')
    if kind == 'normal' and channels < 3:
        warnings.append('Normal map has fewer than 3 channels.')
    if dynamic == 0:
        warnings.append('Map has zero dynamic range.')
    return PBRMapReport(
        path=str(path), kind=kind, width=width, height=height, channels=channels,
        bit_depth=bit_depth, expected_color_space=expected, inferred_udim=_udim(path),
        finite_ratio=finite_ratio, dynamic_range=dynamic, warnings=warnings,
    )
