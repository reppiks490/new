import numpy as np
import pytest
from PIL import Image

from app.world.biome_texture_synthesis import (
    MAX_TEXTURE_SIZE,
    StreamingPNGWriter,
    detail_octaves,
    export_biome_texture_maps,
    fbm,
    gradient_noise,
    relief_to_normal,
    synthesize_biome_texture_maps,
)
from app.world.biomes import Biome, classify_biomes
from app.world.terrain import TerrainSpec, diamond_square_heightmap


def _hm(seed=1, power=5):
    return diamond_square_heightmap(TerrainSpec(name="t", size_meters=100, resolution_power=power, height_scale_meters=20, roughness=0.6, seed=seed))


def test_gradient_noise_bounded_deterministic_and_continuous():
    x = np.linspace(0, 8, 400)[None, :]
    y = np.linspace(0, 8, 400)[:, None]
    a = gradient_noise(x, y, 5)
    assert np.array_equal(a, gradient_noise(x, y, 5))
    assert np.abs(a).max() <= 1.05
    assert np.abs(np.diff(a, axis=1)).max() < 0.1  # continuous, not white noise


def test_fbm_rejects_zero_octaves():
    with pytest.raises(ValueError):
        fbm(np.zeros((1, 4)), np.zeros((4, 1)), base_frequency=4, octaves=0, seed=0)


def test_detail_octaves_grow_with_resolution():
    assert detail_octaves(64) < detail_octaves(2048) < detail_octaves(16384)


def test_output_is_identical_regardless_of_banding_and_threads():
    hm = _hm()
    a = synthesize_biome_texture_maps(hm, texture_size=128, seed=3, band_rows=128, workers=1)
    b = synthesize_biome_texture_maps(hm, texture_size=128, seed=3, band_rows=13, workers=4)
    for key in a:
        assert np.array_equal(a[key], b[key]), key


def test_shapes_and_dtypes():
    maps = synthesize_biome_texture_maps(_hm(), texture_size=64, seed=1)
    assert maps["basecolor"].shape == (64, 64, 3) and maps["basecolor"].dtype == np.uint8
    assert maps["roughness"].shape == (64, 64) and maps["roughness"].dtype == np.uint8
    assert maps["normal"].shape == (64, 64, 3) and maps["normal"].dtype == np.uint8


@pytest.mark.parametrize("bad", [0, 4, MAX_TEXTURE_SIZE + 1])
def test_rejects_out_of_range_texture_size(bad):
    with pytest.raises(ValueError):
        synthesize_biome_texture_maps(_hm(), texture_size=bad)


def test_rejects_non_square_or_non_finite_heightmap():
    with pytest.raises(ValueError):
        synthesize_biome_texture_maps(np.zeros((4, 5)), texture_size=16)
    bad = _hm()
    bad[0, 0] = np.nan
    with pytest.raises(ValueError):
        synthesize_biome_texture_maps(bad, texture_size=16)


def test_seed_changes_output():
    hm = _hm()
    a = synthesize_biome_texture_maps(hm, texture_size=64, seed=1)["basecolor"]
    b = synthesize_biome_texture_maps(hm, texture_size=64, seed=2)["basecolor"]
    assert not np.array_equal(a, b)


def test_texture_aligns_with_terrain_biomes_at_vertex_locations():
    # Sample the texture at each vertex's pixel (row r, col c -> same image
    # row/col, the mapping terrain_uvs encodes) and check colors match the
    # vertex's own biome: proves orientation and registration, not just
    # "some water exists somewhere".
    hm = _hm(power=5)
    size = 512
    base = synthesize_biome_texture_maps(hm, texture_size=size, seed=1)["basecolor"].astype(int)
    labels = classify_biomes(hm)
    n = hm.shape[0]
    idx = np.minimum((np.arange(n) / (n - 1) * size).astype(int), size - 1)
    samples = base[np.ix_(idx, idx)]
    r, g, b = samples[..., 0], samples[..., 1], samples[..., 2]
    water = labels == Biome.WATER.value
    forest = labels == Biome.FOREST.value
    assert water.sum() > 5 and forest.sum() > 5
    assert ((b > r + 20) & (b > g))[water].mean() > 0.85
    assert ((g > r) & (g > b))[forest].mean() > 0.85


def test_normal_map_follows_gltf_convention():
    size = 32
    ramp_right = np.tile(np.linspace(0, 0.01, size), (size, 1))  # rises toward +col
    n = relief_to_normal(ramp_right, texture_size=size).astype(int)
    assert (n[..., 0] < 128).all()  # normal leans left (-X)
    ramp_down = ramp_right.T  # rises toward +row (down the image)
    n = relief_to_normal(ramp_down, texture_size=size).astype(int)
    assert (n[..., 1] > 128).all()  # leans image-up (+Y)
    flat = relief_to_normal(np.zeros((8, 8)), texture_size=8)
    assert (flat == [128, 128, 255]).all()


def test_water_is_smoother_than_rock_in_roughness():
    maps = synthesize_biome_texture_maps(np.zeros((17, 17)), texture_size=64, seed=1)
    assert maps["roughness"].mean() < 40


def test_larger_texture_carries_more_fine_detail():
    hm = _hm()
    small = synthesize_biome_texture_maps(hm, texture_size=128, seed=1)["basecolor"]
    large = synthesize_biome_texture_maps(hm, texture_size=512, seed=1)["basecolor"].astype(float)
    # A real 512 synthesis must carry more pixel-scale detail than the 128
    # one stretched 4x -- i.e. resolution adds detail, not just pixels.
    stretched = np.asarray(Image.fromarray(small).resize((512, 512), Image.BICUBIC)).astype(float)
    large_hf = np.abs(np.diff(large, axis=1)).mean()
    stretched_hf = np.abs(np.diff(stretched, axis=1)).mean()
    assert large_hf > stretched_hf * 1.5


def test_export_streams_valid_pngs_matching_in_memory_synthesis(tmp_path):
    hm = _hm()
    paths = export_biome_texture_maps(
        hm, texture_size=96, basecolor_path=tmp_path / "b.png", roughness_path=tmp_path / "r.png",
        normal_path=tmp_path / "n.png", seed=4, band_rows=10,
    )
    mem = synthesize_biome_texture_maps(hm, texture_size=96, seed=4)
    for key, mode in (("basecolor", "RGB"), ("roughness", "L"), ("normal", "RGB")):
        with Image.open(paths[f"{key}_path"]) as im:
            im.load()
            assert im.mode == mode and im.size == (96, 96)
            assert np.array_equal(np.asarray(im), mem[key])


def test_normal_path_is_optional(tmp_path):
    paths = export_biome_texture_maps(_hm(), texture_size=32, basecolor_path=tmp_path / "b.png", roughness_path=tmp_path / "r.png")
    assert "normal_path" not in paths


def test_streaming_writer_rejects_incomplete_image(tmp_path):
    w = StreamingPNGWriter(tmp_path / "x.png", 4, 4, 1)
    w.write_rows(np.zeros((2, 4), dtype=np.uint8))
    with pytest.raises(ValueError):
        w.close()
    w2 = StreamingPNGWriter(tmp_path / "y.png", 4, 4, 1)
    with pytest.raises(ValueError):
        w2.write_rows(np.zeros((5, 4), dtype=np.uint8))
    w2.abort()
    assert not (tmp_path / "y.png").exists()
