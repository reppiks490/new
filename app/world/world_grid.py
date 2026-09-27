from __future__ import annotations

import math

import numpy as np
import trimesh
from pydantic import BaseModel, Field, model_validator

from app.world.terrain import TerrainSpec, diamond_square_heightmap, heightmap_to_mesh


class WorldGridSpec(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # One master heightmap (2**power + 1 per side) covers the whole world grid
    # and is sliced into tiles, rather than generating each tile's terrain
    # independently -- independent per-tile diamond-square runs would not
    # agree at shared borders. Slicing one array guarantees adjacent tiles
    # share their boundary row/column exactly.
    world_resolution_power: int = Field(default=8, ge=2, le=12)
    tile_count_x: int = Field(default=4, ge=1, le=32)
    tile_count_z: int = Field(default=4, ge=1, le=32)
    tile_size_meters: float = Field(gt=0, le=10_000)
    height_scale_meters: float = Field(gt=0, le=10_000)
    seed: int = 0
    roughness: float = Field(default=0.95, gt=0, le=1.5)  # higher = smoother; see TerrainSpec

    @model_validator(mode="after")
    def validate_tiling(self):
        n = 2 ** self.world_resolution_power
        if n % self.tile_count_x != 0 or n % self.tile_count_z != 0:
            raise ValueError(
                f"a {n}x{n}-sample master heightmap (world_resolution_power="
                f"{self.world_resolution_power}) does not divide evenly into "
                f"{self.tile_count_x}x{self.tile_count_z} tiles"
            )
        return self

    @property
    def samples_per_tile_x(self) -> int:
        return (2 ** self.world_resolution_power) // self.tile_count_x

    @property
    def samples_per_tile_z(self) -> int:
        return (2 ** self.world_resolution_power) // self.tile_count_z


def generate_master_heightmap(spec: WorldGridSpec) -> np.ndarray:
    terrain_spec = TerrainSpec(
        name=spec.name,
        size_meters=spec.tile_size_meters * max(spec.tile_count_x, spec.tile_count_z),
        resolution_power=spec.world_resolution_power,
        height_scale_meters=spec.height_scale_meters,
        seed=spec.seed,
        roughness=spec.roughness,
    )
    return diamond_square_heightmap(terrain_spec)


def extract_tile_heightmap(master: np.ndarray, spec: WorldGridSpec, tile_x: int, tile_z: int) -> np.ndarray:
    if not (0 <= tile_x < spec.tile_count_x and 0 <= tile_z < spec.tile_count_z):
        raise ValueError(f"tile ({tile_x}, {tile_z}) is out of range for a {spec.tile_count_x}x{spec.tile_count_z} grid")
    sx, sz = spec.samples_per_tile_x, spec.samples_per_tile_z
    x0, z0 = tile_x * sx, tile_z * sz
    # +1 sample so this tile's far edge shares an exact row/column of values
    # with its neighbor's near edge -- true seam continuity, not an
    # approximation, because it is literally the same underlying array.
    return master[z0:z0 + sz + 1, x0:x0 + sx + 1]


def tile_mesh(
    master: np.ndarray,
    spec: WorldGridSpec,
    tile_x: int,
    tile_z: int,
    *,
    lod: int = 0,
    with_biomes: bool = False,
    biome_thresholds=None,
) -> trimesh.Trimesh:
    heightmap = extract_tile_heightmap(master, spec, tile_x, tile_z)
    if lod > 0:
        step = 2 ** lod
        heightmap = heightmap[::step, ::step]
    mesh = heightmap_to_mesh(heightmap, size_meters=spec.tile_size_meters, height_scale_meters=spec.height_scale_meters)
    if with_biomes:
        # Classify on the SAME (possibly LOD-downsampled) heightmap the mesh
        # was just built from, so labels and vertices stay index-aligned at
        # every LOD level, not just LOD0.
        from app.world.biomes import biome_vertex_colors, classify_biomes

        labels = classify_biomes(heightmap, biome_thresholds)
        mesh.visual.vertex_colors = biome_vertex_colors(labels)
    return mesh


class WorldStreamingManager:
    """Distance-based tile loading/eviction and LOD selection over a
    WorldGridSpec's master heightmap. This is real, testable business
    logic (which tiles are needed, at what LOD, and cache eviction of
    tiles no longer in view) -- not a rendered viewport, which this
    text-only environment has no GUI toolkit to build.
    """

    def __init__(
        self,
        spec: WorldGridSpec,
        *,
        lod_distances: tuple[float, ...] = (200.0, 500.0, 1000.0),
        with_biomes: bool = True,
    ):
        self.spec = spec
        self.lod_distances = lod_distances
        self.with_biomes = with_biomes
        self._master: np.ndarray | None = None
        self._tile_cache: dict[tuple[int, int, int], trimesh.Trimesh] = {}

    @property
    def master(self) -> np.ndarray:
        if self._master is None:
            self._master = generate_master_heightmap(self.spec)
        return self._master

    def lod_for_distance(self, distance_meters: float) -> int:
        for level, threshold in enumerate(self.lod_distances):
            if distance_meters <= threshold:
                return level
        return len(self.lod_distances)

    def _tile_center(self, tile_x: int, tile_z: int) -> tuple[float, float]:
        return (
            (tile_x + 0.5) * self.spec.tile_size_meters,
            (tile_z + 0.5) * self.spec.tile_size_meters,
        )

    def _distance_to_tile(self, viewer_xz: tuple[float, float], tile_x: int, tile_z: int) -> float:
        cx, cz = self._tile_center(tile_x, tile_z)
        return math.hypot(cx - viewer_xz[0], cz - viewer_xz[1])

    def tiles_in_view(self, viewer_xz: tuple[float, float], view_distance_meters: float) -> list[tuple[int, int]]:
        return [
            (tx, tz)
            for tz in range(self.spec.tile_count_z)
            for tx in range(self.spec.tile_count_x)
            if self._distance_to_tile(viewer_xz, tx, tz) <= view_distance_meters
        ]

    def load_tile(self, tile_x: int, tile_z: int, *, lod: int) -> trimesh.Trimesh:
        key = (tile_x, tile_z, lod)
        if key not in self._tile_cache:
            self._tile_cache[key] = tile_mesh(
                self.master, self.spec, tile_x, tile_z, lod=lod, with_biomes=self.with_biomes,
            )
        return self._tile_cache[key]

    def update(self, viewer_xz: tuple[float, float], view_distance_meters: float) -> dict[tuple[int, int], trimesh.Trimesh]:
        """Load every tile currently in view at its distance-appropriate LOD,
        and evict cached tiles that are no longer needed at all (bounding
        memory -- an actual streaming concern, not an unbounded cache)."""
        in_view = self.tiles_in_view(viewer_xz, view_distance_meters)
        needed: dict[tuple[int, int], int] = {
            (tx, tz): self.lod_for_distance(self._distance_to_tile(viewer_xz, tx, tz))
            for tx, tz in in_view
        }
        needed_keys = {(tx, tz, lod) for (tx, tz), lod in needed.items()}
        for key in list(self._tile_cache):
            if key not in needed_keys:
                del self._tile_cache[key]
        return {(tx, tz): self.load_tile(tx, tz, lod=lod) for (tx, tz), lod in needed.items()}
