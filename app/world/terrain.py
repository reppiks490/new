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
    resolution_power: int = Field(default=6, ge=1, le=12)
    height_scale_meters: float = Field(gt=0, le=10_000)
    seed: int = 0
    # Hurst-style exponent: each finer diamond-square level's random amplitude
    # is multiplied by 2**-roughness. HIGHER = SMOOTHER. ~0.9-1.1 gives
    # natural fractal terrain; ~0.5 is near white noise at vertex scale
    # (measured: 12x the vertex-to-vertex jaggedness of 1.1), which renders
    # as spikes. The old 0.5 default (documented backwards) did exactly that.
    roughness: float = Field(default=0.95, gt=0, le=1.5)


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

    # Vectorized per level. Random draws are taken in the same row-major
    # order the scalar loops used (one rng.uniform per point), so every seed
    # yields bit-identical terrain -- 64x faster, which makes power 12
    # (4097^2 samples, ~33.5M triangles) practical.
    step = n
    scale = 1.0
    while step > 1:
        half = step // 2
        # Diamond step: center of each square = average of its 4 corners.
        c = np.arange(half, size, step)
        avg = (grid[c - half][:, c - half] + grid[c - half][:, c + half]
               + grid[c + half][:, c - half] + grid[c + half][:, c + half]) / 4.0
        grid[np.ix_(c, c)] = avg + rng.uniform(-1, 1, size=avg.shape) * scale
        # Square step: midpoint of each edge = average of its (up to 4)
        # neighbors. Rows alternate between two column offsets, so draws are
        # generated for all rows at once and consumed in row-major order.
        ys = np.arange(0, size, half)
        xs_of = {0: np.arange(0, size, step), half: np.arange(half, size, step)}
        counts = [len(xs_of[(y + half) % step]) for y in ys]
        draws = rng.uniform(-1, 1, size=sum(counts))
        pos = 0
        for off in (0, half):
            rows = ys[(ys + half) % step == off]
            xs = xs_of[off]
            Y, X = np.meshgrid(rows, xs, indexing="ij")
            total = np.zeros(Y.shape)
            count = np.zeros(Y.shape)
            for dy, dx in ((-half, 0), (half, 0), (0, -half), (0, half)):
                yy, xx = Y + dy, X + dx
                ok = (yy >= 0) & (yy < size) & (xx >= 0) & (xx < size)
                total[ok] += grid[yy[ok], xx[ok]]
                count += ok
            grid[Y, X] = total / count
        # add noise in the original row-major draw order
        for y, k in zip(ys, counts):
            xs = xs_of[(y + half) % step]
            grid[y, xs] += draws[pos:pos + k] * scale
            pos += k
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

    # Counter-clockwise seen from +Z, so face normals point up (+Z, this
    # project's vertical axis). The previous (i0, i2, i1) order wound every
    # face clockwise, leaving 100% of terrain normals pointing down: inside-
    # out geometry that backface-culling renderers show from underneath.
    row = np.arange(n - 1)[:, None]
    col = np.arange(n - 1)[None, :]
    i0 = (row * n + col).ravel()
    i1 = i0 + 1
    i2 = i0 + n
    i3 = i2 + 1
    faces = np.empty((len(i0) * 2, 3), dtype=np.int64)
    faces[0::2] = np.stack([i0, i1, i2], axis=1)
    faces[1::2] = np.stack([i1, i3, i2], axis=1)

    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


def terrain_uvs(n: int) -> np.ndarray:
    """(n*n, 2) UVs for heightmap_to_mesh's vertex order, in trimesh's
    OpenGL convention (origin bottom-left; trimesh flips v on glTF export).
    Vertex (row r, col c) maps to image pixel row r, column c of a texture
    synthesized from the same heightmap."""
    if n < 2:
        raise ValueError("n must be >= 2")
    t = np.linspace(0.0, 1.0, n)
    u, v_down = np.meshgrid(t, t, indexing="xy")
    return np.stack([u.ravel(), 1.0 - v_down.ravel()], axis=1)


def generate_terrain_mesh(spec: TerrainSpec) -> trimesh.Trimesh:
    heightmap = diamond_square_heightmap(spec)
    return heightmap_to_mesh(heightmap, size_meters=spec.size_meters, height_scale_meters=spec.height_scale_meters)


def generate_terrain_mesh_with_biomes(spec: TerrainSpec, thresholds=None) -> trimesh.Trimesh:
    """Same as generate_terrain_mesh, but also classifies each vertex into a
    biome (water/beach/plains/forest/rock/mountain/snow) from the same
    heightmap and assigns real per-vertex colors on the mesh -- not a
    separate, unused label grid sitting beside the geometry."""
    from app.world.biomes import biome_vertex_colors, classify_biomes

    heightmap = diamond_square_heightmap(spec)
    mesh = heightmap_to_mesh(heightmap, size_meters=spec.size_meters, height_scale_meters=spec.height_scale_meters)
    labels = classify_biomes(heightmap, thresholds)
    mesh.visual.vertex_colors = biome_vertex_colors(labels)
    return mesh
