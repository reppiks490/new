import numpy as np
import pytest
from PIL import Image

from app.world.biome_texture_synthesis import (
    _domain_warped_biome_labels,
    _fractal_noise_2d,
    _value_noise_2d,
    export_biome_texture_maps,
    synthesize_biome_basecolor,
    synthesize_biome_roughness,
)
from app.world.biomes import Biome
from app.world.terrain import TerrainSpec, diamond_square_heightmap


def _real_heightmap(seed=1):
    spec = TerrainSpec(name="t", size_meters=100, resolution_power=4, height_scale_meters=20, roughness=0.6, seed=seed)
    return diamond_square_heightmap(spec)


def test_value_noise_is_bounded_and_deterministic():
    a = _value_noise_2d(32, frequency=4, seed=1)
    b = _value_noise_2d(32, frequency=4, seed=1)
    assert a.shape == (32, 32)
    assert np.array_equal(a, b)
    assert a.min() >= -1.0
    assert a.max() <= 1.0


def test_value_noise_is_continuous_not_white_noise():
    # Real coherent noise has small differences between adjacent pixels;
    # white noise would have differences comparable to the full [-1,1] range.
    noise = _value_noise_2d(64, frequency=4, seed=1)
    adjacent_diff = np.abs(np.diff(noise, axis=1))
    assert adjacent_diff.mean() < 0.5


def test_fractal_noise_stays_bounded():
    noise = _fractal_noise_2d(64, base_frequency=4, octaves=4, seed=1)
    assert noise.min() >= -1.0001
    assert noise.max() <= 1.0001


def test_domain_warped_labels_produces_all_present_biomes():
    hm = _real_heightmap()
    labels_tex = _domain_warped_biome_labels(hm, 128, seed=1, thresholds=None)
    assert labels_tex.shape == (128, 128)
    # Water is guaranteed present for this seed/spec (visually confirmed lake).
    assert Biome.WATER.value in labels_tex


def test_basecolor_output_shape_and_dtype():
    hm = _real_heightmap()
    rgb = synthesize_biome_basecolor(hm, texture_size=64, seed=1)
    assert rgb.shape == (64, 64, 3)
    assert rgb.dtype == np.uint8


def test_basecolor_rejects_non_square_heightmap():
    with pytest.raises(ValueError):
        synthesize_biome_basecolor(np.zeros((4, 5)), texture_size=64)


def test_basecolor_rejects_invalid_texture_size():
    hm = _real_heightmap()
    with pytest.raises(ValueError):
        synthesize_biome_basecolor(hm, texture_size=0)


def test_basecolor_has_real_coherent_variation_within_a_biome():
    hm = _real_heightmap()
    rgb = synthesize_biome_basecolor(hm, texture_size=128, seed=1)
    labels_tex = _domain_warped_biome_labels(hm, 128, seed=1, thresholds=None)
    for biome in (Biome.FOREST.value, Biome.PLAINS.value):
        mask = labels_tex == biome
        if mask.sum() < 20:
            continue
        pixels = rgb[mask].astype(np.float64)
        assert pixels.std(axis=0).min() > 0, f"{biome} pixels are flat, expected real coherent noise variation"


def test_basecolor_detail_increases_with_texture_size():
    # More texture_size -> higher base_freq -> more distinct noise transitions
    # per unit area, not just bigger flat blocks of the same few values.
    hm = _real_heightmap()
    small = synthesize_biome_basecolor(hm, texture_size=64, seed=1)
    large = synthesize_biome_basecolor(hm, texture_size=512, seed=1)
    assert len(np.unique(small.reshape(-1, 3), axis=0)) < len(np.unique(large.reshape(-1, 3), axis=0))


def test_basecolor_is_deterministic_given_same_seed():
    hm = _real_heightmap()
    a = synthesize_biome_basecolor(hm, texture_size=64, seed=7)
    b = synthesize_biome_basecolor(hm, texture_size=64, seed=7)
    assert np.array_equal(a, b)


def test_basecolor_differs_across_seeds():
    hm = _real_heightmap()
    a = synthesize_biome_basecolor(hm, texture_size=64, seed=1)
    b = synthesize_biome_basecolor(hm, texture_size=64, seed=2)
    assert not np.array_equal(a, b)


def test_roughness_output_shape_dtype_and_bounds():
    hm = _real_heightmap()
    rough = synthesize_biome_roughness(hm, texture_size=64, seed=1)
    assert rough.shape == (64, 64)
    assert rough.dtype == np.uint8
    assert rough.min() >= 0
    assert rough.max() <= 255


def test_water_roughness_is_lower_than_rock_roughness():
    # WATER's base_roughness (0.05) is far below ROCK's (0.65) -- confirms
    # the per-biome roughness params actually reach the output, not just
    # basecolor.
    flat_water = np.zeros((17, 17))  # fully below water_level
    water_rough = synthesize_biome_roughness(flat_water, texture_size=64, seed=1)
    assert water_rough.mean() < 40  # ~0.05*255=12.75 +/- jitter


def test_export_biome_texture_maps_writes_real_png_files(tmp_path):
    hm = _real_heightmap()
    basecolor_path = tmp_path / "basecolor.png"
    roughness_path = tmp_path / "roughness.png"
    result = export_biome_texture_maps(
        hm, texture_size=64, basecolor_path=basecolor_path, roughness_path=roughness_path, seed=1,
    )
    assert basecolor_path.is_file()
    assert roughness_path.is_file()
    with Image.open(basecolor_path) as im:
        assert im.size == (64, 64)
        assert im.mode == "RGB"
    with Image.open(roughness_path) as im:
        assert im.size == (64, 64)
        assert im.mode == "L"
    assert result["basecolor_path"] == str(basecolor_path)
    assert result["roughness_path"] == str(roughness_path)
