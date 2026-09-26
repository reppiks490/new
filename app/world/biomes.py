from __future__ import annotations

from enum import Enum
import numpy as np
from pydantic import BaseModel, Field


class Biome(str, Enum):
    WATER = "water"
    BEACH = "beach"
    PLAINS = "plains"
    FOREST = "forest"
    ROCK = "rock"  # steep slope, regardless of elevation band
    MOUNTAIN = "mountain"
    SNOW = "snow"


class BiomeThresholds(BaseModel):
    # All thresholds are in normalized [0, 1] heightmap units -- the same
    # scale app.world.terrain.diamond_square_heightmap already produces --
    # so this composes directly with existing terrain generation without
    # needing real-world units or a separate elevation pass.
    water_level: float = Field(default=0.28, ge=0, le=1)
    beach_width: float = Field(default=0.04, gt=0, le=0.5)
    forest_max: float = Field(default=0.55, ge=0, le=1)
    mountain_min: float = Field(default=0.75, ge=0, le=1)
    snow_min: float = Field(default=0.88, ge=0, le=1)
    # Local slope magnitude (height-gradient units per grid cell) at or above
    # this classifies ROCK regardless of elevation band, except underwater
    # or snow-capped terrain (see classify_biomes).
    steep_slope_threshold: float = Field(default=0.12, gt=0)

    def validate_monotonic(self) -> None:
        if not (self.water_level < self.forest_max < self.mountain_min < self.snow_min):
            raise ValueError(
                "BiomeThresholds must satisfy water_level < forest_max < mountain_min < snow_min"
            )


def _slope(heightmap: np.ndarray) -> np.ndarray:
    gy, gx = np.gradient(heightmap)
    return np.sqrt(gx * gx + gy * gy)


def classify_biomes(heightmap: np.ndarray, thresholds: BiomeThresholds | None = None) -> np.ndarray:
    """Deterministic elevation + slope biome classification over a normalized
    [0, 1] heightmap grid (as produced by
    app.world.terrain.diamond_square_heightmap). Returns a same-shape object
    array of Biome string values.

    Real, local computation -- no external biome/climate dataset or ML model
    involved, consistent with this project's execution-truth discipline.
    """
    t = thresholds or BiomeThresholds()
    t.validate_monotonic()

    slope = _slope(heightmap)
    labels = np.full(heightmap.shape, Biome.PLAINS.value, dtype=object)

    labels[heightmap < t.water_level] = Biome.WATER.value
    beach_band = (heightmap >= t.water_level) & (heightmap < t.water_level + t.beach_width)
    labels[beach_band] = Biome.BEACH.value
    forest_band = (heightmap >= t.water_level + t.beach_width) & (heightmap < t.forest_max)
    labels[forest_band] = Biome.FOREST.value
    mountain_band = (heightmap >= t.mountain_min) & (heightmap < t.snow_min)
    labels[mountain_band] = Biome.MOUNTAIN.value
    labels[heightmap >= t.snow_min] = Biome.SNOW.value

    # Slope overrides elevation-only classification (a steep mid-elevation
    # cliff is rock, not forest/plains), but never overrides water or snow:
    # a steep underwater slope is still water, and a steep snow-capped peak
    # is still snow rather than becoming "rock."
    steep = slope >= t.steep_slope_threshold
    override_eligible = ~np.isin(labels, [Biome.WATER.value, Biome.SNOW.value])
    labels[steep & override_eligible] = Biome.ROCK.value

    return labels


_BIOME_COLORS: dict[str, tuple[int, int, int, int]] = {
    Biome.WATER.value: (30, 80, 160, 255),
    Biome.BEACH.value: (210, 190, 140, 255),
    Biome.PLAINS.value: (90, 140, 60, 255),
    Biome.FOREST.value: (35, 90, 40, 255),
    Biome.ROCK.value: (110, 100, 95, 255),
    Biome.MOUNTAIN.value: (140, 130, 125, 255),
    Biome.SNOW.value: (240, 240, 245, 255),
}


def biome_vertex_colors(biome_labels: np.ndarray) -> np.ndarray:
    """Map an (n, n) biome-label grid to (n*n, 4) uint8 vertex colors, in the
    same row-major vertex ordering app.world.terrain.heightmap_to_mesh uses
    (both derive from the same (n, n) grid raveled in default C order, so
    index i in the label grid's .ravel() always corresponds to vertex i)."""
    flat = biome_labels.ravel()
    colors = np.zeros((flat.size, 4), dtype=np.uint8)
    for label, rgba in _BIOME_COLORS.items():
        colors[flat == label] = rgba
    return colors
