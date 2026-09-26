from __future__ import annotations

import numpy as np
import trimesh
from pydantic import BaseModel, Field


class TerrainSpec(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    size_meters: float = Field(gt=0, le=100_000)
    # Heightmap grid is (2**resolution_power + 1) per side, as required by the
    # diamond-square algorithm. power=10 -> 1025x1025 -> ~2.1M triangles, which
    # lands right at this project's existing "2M interchange" compatibility
    # tier (see docs/V11_GEOMETRY_REALISM_PLAN.md) — not engineered to match it,
    # but a useful natural ceiling for a single terrain-mesh instance.
    resolution_power: int = Field(default=6, ge=1, le=10)
    height_scale_meters: float = Field(gt=0, le=10_000)
    seed: int = 0
    # Diamond-square's own roughness/persistence parameter: higher values keep
    # more amplitude at finer iterations (jagged terrain), lower values decay
    # faster (smoother, rolling terrain).
    roughness: float = Field(default=0.5, gt=0, le=1.5)


def diamond_square_heightmap(spec: TerrainSpec) -> np.ndarray:
    """Deterministic, seeded fractal heightmap via the classic diamond-square
    algorithm. No external model, asset, or network fetch involved -- this is
    real local computation (numpy only), not synthetic/placeholder data.
    Returns an (n+1, n+1) grid normalized to [0, 1], n = 2**resolution_power.
    """
    n = 2 ** spec.resolution_power
    size = n + 1
    rng = np.random.default_rng(spec.seed)
    grid = np.zeros((size, size), dtype=np.float64)
    grid[0, 0] = rng.uniform(-1, 1)
    grid[0, n] = rng.uniform(-1, 1)
    grid[n, 0] = rng.uniform(-1, 1)
    grid[n, n] = rng.uniform(-1, 1)

    step = n
    scale = 1.0
    while step > 1:
        half = step // 2
        # Diamond step: center of each square = average of its 4 corners.
        for y in range(half, size, step):
            for x in range(half, size, step):
                avg = (
                    grid[y - half, x - half] + grid[y - half, x + half]
                    + grid[y + half, x - half] + grid[y + half, x + half]
                ) / 4.0
                grid[y, x] = avg + rng.uniform(-1, 1) * scale
        # Square step: midpoint of each edge = average of its (up to 4) neighbors.
        for y in range(0, size, half):
            for x in range((y + half) % step, size, step):
                total = 0.0
                count = 0
                if y - half >= 0:
                    total += grid[y - half, x]; count += 1
                if y + half < size:
                    total += grid[y + half, x]; count += 1
                if x - half >= 0:
                    total += grid[y, x - half]; count += 1
                if x + half < size:
                    total += grid[y, x + half]; count += 1
                grid[y, x] = total / count + rng.uniform(-1, 1) * scale
        step = half
        scale *= 2 ** -spec.roughness

    lo, hi = grid.min(), grid.max()
    if hi - lo < 1e-12:
        return np.zeros_like(grid)
    return (grid - lo) / (hi - lo)


def heightmap_to_mesh(heightmap: np.ndarray, *, size_meters: float, height_scale_meters: float) -> trimesh.Trimesh:
    """Convert a normalized [0, 1] heightmap grid into a real, exportable
    triangle mesh: one vertex per grid cell, two triangles per grid quad.
    """
    if heightmap.ndim != 2 or heightmap.shape[0] != heightmap.shape[1]:
        raise ValueError("heightmap must be a square 2D array")
    n = heightmap.shape[0]
    if n < 2:
        raise ValueError("heightmap must be at least 2x2")

    xs = np.linspace(0.0, size_meters, n)
    ys = np.linspace(0.0, size_meters, n)
    gx, gy = np.meshgrid(xs, ys, indexing="xy")
    gz = heightmap * height_scale_meters
    vertices = np.stack([gx.ravel(), gy.ravel(), gz.ravel()], axis=1)

    faces = []
    for row in range(n - 1):
        for col in range(n - 1):
            i0 = row * n + col
            i1 = i0 + 1
            i2 = i0 + n
            i3 = i2 + 1
            faces.append((i0, i2, i1))
            faces.append((i1, i2, i3))

    return trimesh.Trimesh(vertices=vertices, faces=np.asarray(faces, dtype=np.int64), process=False)


def generate_terrain_mesh(spec: TerrainSpec) -> trimesh.Trimesh:
    heightmap = diamond_square_heightmap(spec)
    return heightmap_to_mesh(heightmap, size_meters=spec.size_meters, height_scale_meters=spec.height_scale_meters)
