from __future__ import annotations

"""Production biome texture synthesis: bakes a terrain heightmap into real
PBR texture maps -- sRGB basecolor, linear roughness, and a glTF-convention
tangent-space normal map -- at up to 16384x16384.

How detail is produced, and why:
- Stateless hash-based 2D gradient noise (quintic fade, 16 gradient
  directions), summed as fBm. Noise at a pixel depends only on its global
  texture coordinate, so output is identical however it is banded or
  parallelized, and memory does not grow with frequency (a precomputed
  lattice for the top octave of a 16K texture would need ~1e9 entries).
- The detail octave count grows with texture_size until the top octave sits
  at ~4 pixels per cycle, so a larger texture carries genuinely finer detail
  instead of the same pattern stretched over more pixels.
- Biomes are resolved per pixel on a C2-smooth (cubic B-spline) upsampling
  of the heightmap plus fractal perturbation, then blended with smoothstep
  weights that mirror app.world.biomes.classify_biomes (same thresholds, same
  slope override for rock, water/snow exempt). Boundaries follow terrain
  contours organically; nothing is nearest-neighbor upsampled from the
  coarse grid.
- Colors blend in linear light and are encoded to sRGB once; water shades by
  real depth below the water level, wet sand darkens and smooths near water.
- The normal map encodes per-material micro-relief (ridged rock, canopy
  clumps, sand grain) the mesh cannot carry; the mesh's own vertex normals
  already carry the macro terrain shape, so it is not double-counted.
- Rows are generated in bands on a thread pool (numpy releases the GIL) and
  streamed into PNGs, so peak memory is a few bands, not the whole image.

Deterministic and seeded; real local numpy/scipy computation only.
"""

import itertools
import math
import os
import struct
import zlib
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Iterable, Iterator, TypeVar

import numpy as np
from scipy import ndimage

from app.world.biomes import BiomeThresholds, _slope

MIN_TEXTURE_SIZE = 8
MAX_TEXTURE_SIZE = 16384

# ---------------------------------------------------------------------------
# Noise
# ---------------------------------------------------------------------------

_GRADIENT_ANGLES = np.arange(16) * (2.0 * np.pi / 16.0)
_GRADIENT_X = np.cos(_GRADIENT_ANGLES).astype(np.float32)
_GRADIENT_Y = np.sin(_GRADIENT_ANGLES).astype(np.float32)
_SQRT2 = np.float32(math.sqrt(2.0))

MACRO_BASE_FREQUENCY = 4.0
MACRO_OCTAVES = 4
DETAIL_BASE_FREQUENCY = 12.0


def _hash_lattice(ix: np.ndarray, iy: np.ndarray, seed: int) -> np.ndarray:
    # ix/iy may be a row vector and a column vector; combine them out of
    # place first so the result takes the full broadcast shape.
    h = (ix.astype(np.uint32) * np.uint32(0x8DA6B343)) ^ (iy.astype(np.uint32) * np.uint32(0xD8163841))
    h ^= np.uint32((seed * 0x9E3779B1) & 0xFFFFFFFF)
    h ^= h >> np.uint32(16)
    h *= np.uint32(0x7FEB352D)
    h ^= h >> np.uint32(15)
    h *= np.uint32(0x846CA68B)
    h ^= h >> np.uint32(16)
    return h


def _fade(t: np.ndarray) -> np.ndarray:
    return t * t * t * (t * (t * np.float32(6.0) - np.float32(15.0)) + np.float32(10.0))


def gradient_noise(x: np.ndarray, y: np.ndarray, seed: int) -> np.ndarray:
    """2D gradient noise at lattice coordinates (x, y), approximately in
    [-1, 1], continuous with continuous first and second derivatives."""
    x0 = np.floor(x)
    y0 = np.floor(y)
    fx = (x - x0).astype(np.float32)
    fy = (y - y0).astype(np.float32)
    ix = x0.astype(np.int64)
    iy = y0.astype(np.int64)

    def corner(dx: int, dy: int) -> np.ndarray:
        g = _hash_lattice(ix + dx, iy + dy, seed) & np.uint32(15)
        return _GRADIENT_X[g] * (fx - np.float32(dx)) + _GRADIENT_Y[g] * (fy - np.float32(dy))

    n00, n10, n01, n11 = corner(0, 0), corner(1, 0), corner(0, 1), corner(1, 1)
    u = _fade(fx)
    v = _fade(fy)
    top = n00 + u * (n10 - n00)
    bottom = n01 + u * (n11 - n01)
    return (top + v * (bottom - top)) * _SQRT2


def fbm(u: np.ndarray, v: np.ndarray, *, base_frequency: float, octaves: int, seed: int, gain: float = 0.5) -> np.ndarray:
    """Fractal Brownian motion over texture coordinates (u, v) in [0, 1]:
    octaves at doubling frequency and halving amplitude, normalized."""
    if octaves < 1:
        raise ValueError("octaves must be >= 1")
    total = np.zeros(np.broadcast_shapes(u.shape, v.shape), dtype=np.float32)
    amplitude, norm, frequency = 1.0, 0.0, base_frequency
    for octave in range(octaves):
        total += np.float32(amplitude) * gradient_noise(u * frequency, v * frequency, seed + 7919 * octave)
        norm += amplitude
        amplitude *= gain
        frequency *= 2.0
    return total / np.float32(norm)


def detail_octaves(texture_size: int) -> int:
    """Octave count whose top octave lands at >= 4 pixels per cycle (below
    Nyquist, so it doesn't alias) -- detail density grows with resolution."""
    top_frequency = texture_size / 4.0
    return max(1, int(math.floor(math.log2(max(top_frequency / DETAIL_BASE_FREQUENCY, 1.0)))) + 1)


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------

def _srgb_to_linear(c: np.ndarray) -> np.ndarray:
    c = np.asarray(c, dtype=np.float32) / np.float32(255.0)
    return np.where(c <= 0.04045, c / np.float32(12.92), ((c + np.float32(0.055)) / np.float32(1.055)) ** np.float32(2.4))


def _linear_to_srgb_u8(linear: np.ndarray) -> np.ndarray:
    linear = np.clip(linear, 0.0, 1.0)
    srgb = np.where(
        linear <= 0.0031308,
        linear * np.float32(12.92),
        np.float32(1.055) * linear ** np.float32(1.0 / 2.4) - np.float32(0.055),
    )
    return (srgb * np.float32(255.0) + np.float32(0.5)).astype(np.uint8)


# name -> (sRGB color a, sRGB color b, roughness, roughness variation,
#          brightness grain, micro-relief amplitude, ridged pattern)
# Micro-relief amplitude is in texture-width units (UV space), so a surface's
# bumpiness is a property of the terrain, not of the output resolution: each
# fBm octave contributes the same slope, and a larger texture adds finer
# octaves on top rather than flattening the ones already there.
_MATERIALS: dict[str, tuple[tuple[int, int, int], tuple[int, int, int], float, float, float, float, bool]] = {
    "water": ((58, 150, 170), (14, 46, 102), 0.06, 0.02, 0.03, 0.0002, False),
    "beach": ((224, 206, 162), (198, 178, 132), 0.70, 0.06, 0.10, 0.0012, False),
    "forest": ((34, 78, 36), (60, 100, 42), 0.84, 0.06, 0.30, 0.0040, False),
    "plains": ((82, 136, 54), (146, 150, 82), 0.78, 0.06, 0.16, 0.0020, False),
    "rock": ((104, 97, 93), (134, 116, 98), 0.62, 0.12, 0.30, 0.0100, True),
    "mountain": ((126, 122, 118), (156, 150, 142), 0.66, 0.10, 0.22, 0.0065, True),
    "snow": ((238, 242, 250), (212, 222, 240), 0.36, 0.06, 0.05, 0.0013, False),
}
_MATERIAL_LINEAR = {
    name: (_srgb_to_linear(a), _srgb_to_linear(b)) for name, (a, b, *_rest) in _MATERIALS.items()
}

# Pixel-scale brightness grain per material (linear-light fraction): crisp
# 1:1 detail such as sand grain, grass blades, rock speckle, snow sparkle.
_PIXEL_GRAIN = {"water": 0.06, "beach": 0.35, "forest": 0.55, "plains": 0.45, "rock": 0.5, "mountain": 0.45, "snow": 0.12}

BOUNDARY_SOFTNESS = 0.004  # half-width of elevation band transitions, normalized height units
BOUNDARY_PERTURBATION = 0.018  # fractal contour wiggle amplitude, normalized height units
WATER_DEPTH_FULL = 0.18  # depth below water level at which water reaches its deep color


def _smoothstep(edge0: float, edge1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - np.float32(edge0)) / np.float32(edge1 - edge0), 0.0, 1.0)
    return t * t * (np.float32(3.0) - np.float32(2.0) * t)


def _material_weights(h: np.ndarray, slope: np.ndarray, t: BiomeThresholds) -> dict[str, np.ndarray]:
    """Smoothstep partition of unity over the same bands and slope override
    as classify_biomes: sum of all weights is exactly 1 at every pixel."""
    e = BOUNDARY_SOFTNESS

    def step(edge: float) -> np.ndarray:
        return _smoothstep(edge - e, edge + e, h)

    s_water = step(t.water_level)
    s_beach = step(t.water_level + t.beach_width)
    s_forest = step(t.forest_max)
    s_mountain = step(t.mountain_min)
    s_snow = step(t.snow_min)
    water = 1.0 - s_water
    snow = s_snow
    rock_factor = _smoothstep(t.steep_slope_threshold * 0.8, t.steep_slope_threshold * 1.2, slope)
    keep = 1.0 - rock_factor
    return {
        "water": water,
        "beach": (s_water - s_beach) * keep,
        "forest": (s_beach - s_forest) * keep,
        "plains": (s_forest - s_mountain) * keep,
        "mountain": (s_mountain - s_snow) * keep,
        "rock": rock_factor * (1.0 - water - snow),
        "snow": snow,
    }


def relief_to_normal(relief: np.ndarray, *, texture_size: int) -> np.ndarray:
    """Encode a height field in texture-width (UV) units, rows increasing
    downward, as a glTF tangent-space normal map: +X right, +Y up the image,
    +Z out. n ~ (-dh/du, -dh/dv_up, 1) = (-dh/dcol, +dh/drow, 1) * T, because
    one pixel is 1/T of the texture width and image-up is -row."""
    d_row, d_col = np.gradient(relief.astype(np.float32))
    scale = np.float32(texture_size)
    nx = -d_col * scale
    ny = d_row * scale
    nz = np.ones_like(nx)
    inv_len = np.float32(1.0) / np.sqrt(nx * nx + ny * ny + nz * nz)
    normal = np.stack([nx * inv_len, ny * inv_len, nz * inv_len], axis=-1)
    return ((normal * np.float32(0.5) + np.float32(0.5)) * np.float32(255.0) + np.float32(0.5)).astype(np.uint8)


# ---------------------------------------------------------------------------
# Band synthesis
# ---------------------------------------------------------------------------

class _TerrainTextureField:
    """Everything a band needs that is shared across bands: spline
    coefficients of the heightmap, the coarse slope grid, thresholds."""

    def __init__(self, heightmap: np.ndarray, texture_size: int, seed: int, thresholds: BiomeThresholds | None):
        if heightmap.ndim != 2 or heightmap.shape[0] != heightmap.shape[1]:
            raise ValueError("heightmap must be a square 2D array")
        if heightmap.shape[0] < 2:
            raise ValueError("heightmap must be at least 2x2")
        if not np.isfinite(heightmap).all():
            raise ValueError("heightmap contains non-finite values")
        if not MIN_TEXTURE_SIZE <= texture_size <= MAX_TEXTURE_SIZE:
            raise ValueError(f"texture_size must be between {MIN_TEXTURE_SIZE} and {MAX_TEXTURE_SIZE}")
        self.thresholds = thresholds or BiomeThresholds()
        self.thresholds.validate_monotonic()
        self.n = heightmap.shape[0]
        self.size = texture_size
        self.seed = seed
        self.detail_octaves = detail_octaves(texture_size)
        self.height_coeffs = ndimage.spline_filter(heightmap.astype(np.float64), order=3, mode="nearest")
        self.slope_grid = _slope(heightmap.astype(np.float64))

    def band(self, row_start: int, row_stop: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Basecolor (rows, T, 3) u8 sRGB, roughness (rows, T) u8, normal
        (rows, T, 3) u8 for texture rows [row_start, row_stop)."""
        halo_start = max(0, row_start - 1)
        halo_stop = min(self.size, row_stop + 1)
        rows = np.arange(halo_start, halo_stop, dtype=np.float64)
        cols = np.arange(self.size, dtype=np.float64)
        v = ((rows + 0.5) / self.size)[:, None]
        u = ((cols + 0.5) / self.size)[None, :]
        grid_y = np.broadcast_to(v * (self.n - 1), (len(rows), self.size))
        grid_x = np.broadcast_to(u * (self.n - 1), (len(rows), self.size))
        coords = np.stack([grid_y, grid_x])

        coarse_h = ndimage.map_coordinates(self.height_coeffs, coords, order=3, mode="nearest", prefilter=False).astype(np.float32)
        slope = ndimage.map_coordinates(self.slope_grid, coords, order=1, mode="nearest").astype(np.float32)

        macro = fbm(u, v, base_frequency=MACRO_BASE_FREQUENCY, octaves=MACRO_OCTAVES, seed=self.seed + 101)
        detail = fbm(u, v, base_frequency=DETAIL_BASE_FREQUENCY, octaves=self.detail_octaves, seed=self.seed + 202, gain=0.68)
        # Pixel-scale grain: top octaves only (~4-16 px per cycle), so fine
        # texture is crisp at 1:1 zoom at every resolution.
        grain_field = fbm(u, v, base_frequency=self.size / 5.0, octaves=2, seed=self.seed + 303, gain=0.7)
        ridged = np.float32(1.0) - np.float32(2.0) * np.abs(detail)

        t = self.thresholds
        h = coarse_h + np.float32(BOUNDARY_PERTURBATION) * (np.float32(0.6) * macro + np.float32(0.3) * detail + np.float32(0.25) * grain_field)
        weights = _material_weights(h, slope * (np.float32(1.0) + np.float32(0.25) * macro), t)

        depth_mix = _smoothstep(0.0, WATER_DEPTH_FULL, np.float32(t.water_level) - coarse_h)
        wet = np.float32(1.0) - _smoothstep(t.water_level, t.water_level + t.beach_width * 0.6, h)
        hue_mix = np.clip(np.float32(0.5) + np.float32(0.5) * macro, 0.0, 1.0)

        color = np.zeros(coarse_h.shape + (3,), dtype=np.float32)
        roughness = np.zeros(coarse_h.shape, dtype=np.float32)
        relief = np.zeros(coarse_h.shape, dtype=np.float32)
        for name, (_a, _b, rough, rough_var, grain, relief_amp, is_ridged) in _MATERIALS.items():
            w = weights[name]
            pattern = ridged if is_ridged else detail
            mix = depth_mix if name == "water" else hue_mix
            lin_a, lin_b = _MATERIAL_LINEAR[name]
            base = lin_a + (lin_b - lin_a) * mix[..., None]
            brightness = (np.float32(1.0) + np.float32(grain) * pattern) * (np.float32(1.0) + np.float32(_PIXEL_GRAIN[name]) * grain_field)
            material_rough = np.float32(rough) + np.float32(rough_var) * pattern
            if name == "beach":
                brightness = brightness * (np.float32(1.0) - np.float32(0.35) * wet)
                material_rough = material_rough - np.float32(0.35) * wet
            color += (w * brightness)[..., None] * base
            roughness += w * material_rough
            relief += w * np.float32(relief_amp) * pattern

        keep = slice(row_start - halo_start, row_start - halo_start + (row_stop - row_start))
        normal = relief_to_normal(relief, texture_size=self.size)[keep]
        basecolor = _linear_to_srgb_u8(color[keep])
        roughness_u8 = (np.clip(roughness[keep], 0.02, 1.0) * np.float32(255.0) + np.float32(0.5)).astype(np.uint8)
        return basecolor, roughness_u8, normal


def band_rows_for(texture_size: int) -> int:
    """~1M pixels per band: bounded working memory at any texture size."""
    return int(np.clip((1 << 20) // max(texture_size, 1), 8, 256))


_T = TypeVar("_T")
_R = TypeVar("_R")


def _ordered_parallel(fn: Callable[[_T], _R], items: Iterable[_T], workers: int) -> Iterator[_R]:
    """map() over a thread pool, yielding in input order with a bounded
    number of results in flight (executor.map submits everything up front)."""
    if workers <= 1:
        yield from map(fn, items)
        return
    iterator = iter(items)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = deque(pool.submit(fn, item) for item in itertools.islice(iterator, workers * 2))
        while pending:
            result = pending.popleft().result()
            for item in itertools.islice(iterator, 1):
                pending.append(pool.submit(fn, item))
            yield result


def _iter_bands(field: _TerrainTextureField, band_rows: int | None, workers: int | None):
    rows = band_rows or band_rows_for(field.size)
    spans = [(start, min(start + rows, field.size)) for start in range(0, field.size, rows)]
    worker_count = workers if workers is not None else min(4, os.cpu_count() or 1)
    return _ordered_parallel(lambda span: field.band(*span), spans, worker_count)


def synthesize_biome_texture_maps(
    heightmap: np.ndarray,
    *,
    texture_size: int,
    seed: int = 0,
    thresholds: BiomeThresholds | None = None,
    band_rows: int | None = None,
    workers: int | None = None,
) -> dict[str, np.ndarray]:
    """In-memory synthesis: {"basecolor": (T,T,3) u8 sRGB, "roughness": (T,T)
    u8 linear, "normal": (T,T,3) u8 glTF tangent-space}. For large sizes
    prefer export_biome_texture_maps, which streams to disk."""
    field = _TerrainTextureField(heightmap, texture_size, seed, thresholds)
    parts = list(_iter_bands(field, band_rows, workers))
    return {
        "basecolor": np.concatenate([p[0] for p in parts], axis=0),
        "roughness": np.concatenate([p[1] for p in parts], axis=0),
        "normal": np.concatenate([p[2] for p in parts], axis=0),
    }


# ---------------------------------------------------------------------------
# Streaming PNG output
# ---------------------------------------------------------------------------

class StreamingPNGWriter:
    """Minimal spec-conformant PNG encoder (8-bit grayscale or RGB, filter
    type 0, multiple IDAT chunks) fed row bands, so a 16K texture is written
    without ever holding the whole image in memory."""

    _SIGNATURE = b"\x89PNG\r\n\x1a\n"
    _COLOR_TYPES = {1: 0, 3: 2}

    def __init__(self, path: str | Path, width: int, height: int, channels: int, *, compress_level: int = 4, bit_depth: int = 8):
        if channels not in self._COLOR_TYPES:
            raise ValueError("channels must be 1 (grayscale) or 3 (RGB)")
        if bit_depth not in (8, 16):
            raise ValueError("bit_depth must be 8 or 16")
        self.path = Path(path)
        self.width, self.height, self.channels, self.bit_depth = width, height, channels, bit_depth
        self._rows_written = 0
        self._compressor = zlib.compressobj(compress_level)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self.path, "wb")
        self._file.write(self._SIGNATURE)
        self._chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, bit_depth, self._COLOR_TYPES[channels], 0, 0, 0))

    def _chunk(self, tag: bytes, data: bytes) -> None:
        self._file.write(struct.pack(">I", len(data)))
        self._file.write(tag)
        self._file.write(data)
        self._file.write(struct.pack(">I", zlib.crc32(data, zlib.crc32(tag)) & 0xFFFFFFFF))

    def write_rows(self, rows: np.ndarray) -> None:
        count = rows.shape[0]
        if self._rows_written + count > self.height:
            raise ValueError("more rows written than the declared image height")
        if self.bit_depth == 16:  # PNG samples are big-endian
            payload = np.ascontiguousarray(rows, dtype=">u2").reshape(count, self.width * self.channels).view(np.uint8)
        else:
            payload = np.ascontiguousarray(rows, dtype=np.uint8).reshape(count, self.width * self.channels)
        scanlines = np.zeros((count, payload.shape[1] + 1), dtype=np.uint8)  # leading 0 = filter "None"
        scanlines[:, 1:] = payload
        data = self._compressor.compress(scanlines.tobytes())
        if data:
            self._chunk(b"IDAT", data)
        self._rows_written += count

    def close(self) -> None:
        if self._file.closed:
            return
        try:
            if self._rows_written != self.height:
                raise ValueError(f"PNG incomplete: {self._rows_written} of {self.height} rows written")
            tail = self._compressor.flush()
            if tail:
                self._chunk(b"IDAT", tail)
            self._chunk(b"IEND", b"")
        finally:
            self._file.close()

    def abort(self) -> None:
        self._file.close()
        self.path.unlink(missing_ok=True)


def export_biome_texture_maps(
    heightmap: np.ndarray,
    *,
    texture_size: int,
    basecolor_path: str | Path,
    roughness_path: str | Path,
    normal_path: str | Path | None = None,
    metallic_roughness_path: str | Path | None = None,
    seed: int = 0,
    thresholds: BiomeThresholds | None = None,
    band_rows: int | None = None,
    workers: int | None = None,
) -> dict[str, str]:
    """Synthesize and stream the maps to real PNG files with bounded memory.
    metallic_roughness_path adds a glTF-packed map (G = roughness,
    B = metallic = 0, R unused = 255). Partial files are removed if
    generation fails midway."""
    field = _TerrainTextureField(heightmap, texture_size, seed, thresholds)
    writers: list[StreamingPNGWriter] = []
    try:
        writers.append(StreamingPNGWriter(basecolor_path, texture_size, texture_size, 3))
        writers.append(StreamingPNGWriter(roughness_path, texture_size, texture_size, 1))
        normal_writer = mr_writer = None
        if normal_path is not None:
            normal_writer = StreamingPNGWriter(normal_path, texture_size, texture_size, 3)
            writers.append(normal_writer)
        if metallic_roughness_path is not None:
            mr_writer = StreamingPNGWriter(metallic_roughness_path, texture_size, texture_size, 3)
            writers.append(mr_writer)
        for basecolor, roughness, normal in _iter_bands(field, band_rows, workers):
            writers[0].write_rows(basecolor)
            writers[1].write_rows(roughness)
            if normal_writer is not None:
                normal_writer.write_rows(normal)
            if mr_writer is not None:
                mr_writer.write_rows(np.stack([np.full_like(roughness, 255), roughness, np.zeros_like(roughness)], axis=-1))
        for writer in writers:
            writer.close()
    except BaseException:
        for writer in writers:
            writer.abort()
        raise

    result = {"basecolor_path": str(Path(basecolor_path)), "roughness_path": str(Path(roughness_path))}
    if normal_path is not None:
        result["normal_path"] = str(Path(normal_path))
    if metallic_roughness_path is not None:
        result["metallic_roughness_path"] = str(Path(metallic_roughness_path))
    return result


def synthesize_vegetation_density(
    heightmap: np.ndarray,
    *,
    size: int,
    seed: int = 0,
    thresholds: BiomeThresholds | None = None,
) -> np.ndarray:
    """(size, size, 2) uint8: channel 0 = forest weight, channel 1 = plains
    weight, from the same bicubic height, slope, biome thresholds and macro/
    detail noise that paint the ground textures, so scattered trees stand
    exactly where the texture shows forest (rock, snow, water and beach get
    zero). Same texel/UV mapping as the texture maps."""
    field = _TerrainTextureField(heightmap, size, seed, thresholds)
    out = np.empty((size, size, 2), dtype=np.uint8)
    cols = np.arange(size, dtype=np.float64)
    u = ((cols + 0.5) / size)[None, :]
    for r0 in range(0, size, 256):
        rows = np.arange(r0, min(size, r0 + 256), dtype=np.float64)
        v = ((rows + 0.5) / size)[:, None]
        coords = np.stack([np.broadcast_to(v * (field.n - 1), (len(rows), size)),
                           np.broadcast_to(u * (field.n - 1), (len(rows), size))])
        coarse_h = ndimage.map_coordinates(field.height_coeffs, coords, order=3, mode="nearest", prefilter=False).astype(np.float32)
        slope = ndimage.map_coordinates(field.slope_grid, coords, order=1, mode="nearest").astype(np.float32)
        macro = fbm(u, v, base_frequency=MACRO_BASE_FREQUENCY, octaves=MACRO_OCTAVES, seed=seed + 101)
        detail = fbm(u, v, base_frequency=DETAIL_BASE_FREQUENCY, octaves=field.detail_octaves, seed=seed + 202, gain=0.68)
        h = coarse_h + np.float32(BOUNDARY_PERTURBATION) * (np.float32(0.6) * macro + np.float32(0.3) * detail)
        w = _material_weights(h, slope * (np.float32(1.0) + np.float32(0.25) * macro), field.thresholds)
        out[r0:r0 + len(rows), :, 0] = (np.clip(w["forest"], 0, 1) * 255 + 0.5).astype(np.uint8)
        out[r0:r0 + len(rows), :, 1] = (np.clip(w["plains"], 0, 1) * 255 + 0.5).astype(np.uint8)
    return out
