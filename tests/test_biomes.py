import numpy as np
import pytest

from app.world.biomes import Biome, BiomeThresholds, biome_vertex_colors, classify_biomes
from app.world.terrain import TerrainSpec, diamond_square_heightmap, generate_terrain_mesh_with_biomes


def test_flat_heightmap_gives_expected_elevation_bands():
    # Each band is several rows thick and we only check interior rows (away
    # from a band boundary), so np.gradient's central differences never
    # cross into a neighboring band and confound elevation-only
    # classification with the slope override tested separately below.
    hm = np.zeros((12, 4))
    hm[0:3, :] = 0.1     # water
    hm[3:6, :] = 0.4     # forest
    hm[6:9, :] = 0.8     # mountain
    hm[9:12, :] = 0.95   # snow
    labels = classify_biomes(hm)
    assert (labels[1, :] == Biome.WATER.value).all()
    assert (labels[4, :] == Biome.FOREST.value).all()
    assert (labels[7, :] == Biome.MOUNTAIN.value).all()
    assert (labels[10, :] == Biome.SNOW.value).all()


def test_beach_band_sits_between_water_and_forest():
    t = BiomeThresholds(water_level=0.3, beach_width=0.05)
    hm = np.full((2, 2), 0.32)  # inside [0.30, 0.35) beach band
    labels = classify_biomes(hm, t)
    assert (labels == Biome.BEACH.value).all()


def test_steep_slope_overrides_midband_elevation_to_rock():
    # A step boundary steep enough to exceed steep_slope_threshold (0.12)
    # should classify as ROCK at the transition, even though elevation alone
    # on both sides would be forest/plains -- verified via a real gradient
    # probe before choosing these values (slope at the boundary columns is
    # exactly 0.13, just above the 0.12 threshold).
    hm = np.full((5, 6), 0.35)
    hm[:, 3:] = 0.61
    labels = classify_biomes(hm)
    assert labels[2, 2] == Biome.ROCK.value
    assert labels[2, 3] == Biome.ROCK.value
    # Flat away from the boundary: unaffected, elevation-only classification.
    assert labels[2, 0] == Biome.FOREST.value
    assert labels[2, 5] == Biome.PLAINS.value


def test_slope_never_overrides_water_or_snow():
    hm = np.zeros((3, 3))
    hm[1, 1] = 1.0  # a very steep spike straight out of water
    labels = classify_biomes(hm)
    # The spike's own elevation (1.0) is >= snow_min, so it must stay SNOW,
    # not get reclassified to ROCK by its high local slope.
    assert labels[1, 1] == Biome.SNOW.value
    # Its flat neighbors are underwater and must stay WATER despite being
    # adjacent to a steep gradient.
    assert labels[0, 0] == Biome.WATER.value


def test_thresholds_must_be_strictly_increasing():
    with pytest.raises(ValueError):
        classify_biomes(np.zeros((2, 2)), BiomeThresholds(water_level=0.5, forest_max=0.4))


def test_vertex_colors_shape_and_known_label_mapping():
    labels = np.array([[Biome.WATER.value, Biome.SNOW.value]], dtype=object)
    colors = biome_vertex_colors(labels)
    assert colors.shape == (2, 4)
    assert tuple(colors[0]) == (30, 80, 160, 255)
    assert tuple(colors[1]) == (240, 240, 245, 255)


def test_full_pipeline_terrain_mesh_vertex_colors_match_elevation(tmp_path):
    spec = TerrainSpec(name="isle", size_meters=200.0, resolution_power=5, height_scale_meters=40.0, seed=3)
    heightmap = diamond_square_heightmap(spec)
    mesh = generate_terrain_mesh_with_biomes(spec)

    n = heightmap.shape[0]
    assert len(mesh.vertices) == n * n
    colors = np.asarray(mesh.visual.vertex_colors)
    assert colors.shape[0] == n * n

    # Pick a real vertex known to be deep water by its actual height, and
    # confirm the mesh's own stored vertex color at that same index is
    # actually the water color -- verifying the full heightmap -> biome ->
    # mesh-vertex-color pipeline lines up on the real object, not just that
    # the label grid alone looks right.
    flat_heights = heightmap.ravel()
    water_idx = int(np.argmin(flat_heights))
    assert tuple(colors[water_idx][:4]) == (30, 80, 160, 255)

    snow_idx = int(np.argmax(flat_heights))
    assert tuple(colors[snow_idx][:4]) == (240, 240, 245, 255)

    # Every generated color must be one of the defined biome colors -- no
    # stray/uninitialized (0,0,0,0) entries slipping through.
    valid_colors = {(30, 80, 160, 255), (210, 190, 140, 255), (90, 140, 60, 255),
                    (35, 90, 40, 255), (110, 100, 95, 255), (140, 130, 125, 255),
                    (240, 240, 245, 255)}
    unique_colors = {tuple(c) for c in colors[:, :4]}
    assert unique_colors <= valid_colors
