import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.exports.gltf_validation import _load_glb, read_glb_accessor, validate_gltf_structure
from app.main import app
from app.world.terrain import TerrainSpec, terrain_uvs
from app.world.textured_terrain import build_textured_terrain, export_textured_terrain_glb

client = TestClient(app)
SPEC = TerrainSpec(name="vale", size_meters=100, resolution_power=4, height_scale_meters=15, seed=2)


def test_terrain_uvs_map_rows_down_the_image_after_gltf_flip():
    uv = terrain_uvs(3)
    assert np.allclose(uv[0], [0, 1])  # row 0 col 0: top-left in trimesh (bottom-left origin)
    assert np.allclose(uv[2], [1, 1])
    assert np.allclose(uv[6], [0, 0])


def test_glb_is_self_contained_pbr_with_correct_uv_registration(tmp_path):
    out = tmp_path / "vale.glb"
    export_textured_terrain_glb(SPEC, out, texture_size=64)
    report = validate_gltf_structure(out)
    assert report.passed and report.image_count == 3 and report.external_resource_count == 0
    gltf, _ = _load_glb(out)
    material = gltf["materials"][0]
    pbr = material["pbrMetallicRoughness"]
    assert "baseColorTexture" in pbr and "metallicRoughnessTexture" in pbr and "normalTexture" in material
    assert pbr["metallicFactor"] == 0.0
    uv = read_glb_accessor(out, gltf["meshes"][0]["primitives"][0]["attributes"]["TEXCOORD_0"])
    n = 17
    assert np.allclose(uv[0], [0, 0])  # glTF: vertex(row 0, col 0) -> image top-left
    assert np.allclose(uv[n - 1], [1, 0])
    assert np.allclose(uv[n * (n - 1)], [0, 1])


def test_metallic_roughness_channels_follow_gltf_layout():
    mesh = build_textured_terrain(SPEC, texture_size=32)
    mr = np.asarray(mesh.visual.material.metallicRoughnessTexture)
    assert (mr[..., 2] == 0).all()  # B = metallic = 0
    assert mr[..., 1].std() > 0  # G = real per-pixel roughness


@pytest.mark.parametrize("size", [4, 16385])
def test_rejects_texture_size_out_of_range(size):
    with pytest.raises(ValueError):
        build_textured_terrain(SPEC, texture_size=size)


def test_rejects_non_gltf_output(tmp_path):
    with pytest.raises(ValueError):
        export_textured_terrain_glb(SPEC, tmp_path / "x.obj", texture_size=16)


def test_endpoint_writes_textured_glb(tmp_path):
    out = tmp_path / "t.glb"
    r = client.post("/v1/world/terrain/generate-textured", json={
        "terrain": SPEC.model_dump(), "output_path": str(out), "texture_size": 64,
    })
    assert r.status_code == 200, r.text
    assert r.json()["maps"] == ["baseColor", "metallicRoughness", "normal"]
    assert validate_gltf_structure(out).image_count == 3


def test_endpoint_rejects_non_gltf_output_with_422(tmp_path):
    r = client.post("/v1/world/terrain/generate-textured", json={
        "terrain": SPEC.model_dump(), "output_path": str(tmp_path / "t.obj"), "texture_size": 64,
    })
    assert r.status_code == 422


def test_water_is_a_flat_surface_at_the_water_level():
    from app.world.biomes import BiomeThresholds
    from app.world.terrain import diamond_square_heightmap

    spec = TerrainSpec(name="lake", size_meters=100, resolution_power=5, height_scale_meters=20, seed=1)
    mesh = build_textured_terrain(spec, texture_size=32)
    level = BiomeThresholds().water_level * spec.height_scale_meters
    heights = mesh.vertices[:, 2]
    assert (diamond_square_heightmap(spec) < BiomeThresholds().water_level).any()
    assert heights.min() == pytest.approx(level)
    raw = build_textured_terrain(spec, texture_size=32, flatten_water=False)
    assert raw.vertices[:, 2].min() < level


def test_default_terrain_is_not_vertex_scale_noise():
    from app.world.terrain import diamond_square_heightmap

    h = diamond_square_heightmap(TerrainSpec(name="t", size_meters=1000, resolution_power=8, height_scale_meters=200, seed=11))
    lap = np.abs(4 * h[1:-1, 1:-1] - h[:-2, 1:-1] - h[2:, 1:-1] - h[1:-1, :-2] - h[1:-1, 2:]).mean()
    assert lap < 0.03


def test_displacement_residual_is_cubic_surface_minus_bilinear_base_patches():
    from scipy import ndimage

    from app.world.textured_terrain import displacement_residual

    rng = np.random.default_rng(3)
    n, stride, size = 9, 2, 64
    surface = rng.random((n, n))
    res = displacement_residual(surface, size, base_stride=stride)
    assert res.shape == (size, size) and res.dtype == np.float32
    coeffs = ndimage.spline_filter(surface, order=3, mode="nearest")
    # the cubic spline interpolates every sample, and the bilinear base equals
    # the samples at base vertices, so the rendered surface passes through them
    at_samples = ndimage.map_coordinates(coeffs, np.mgrid[0:n, 0:n].reshape(2, -1).astype(float), order=3, mode="nearest", prefilter=False)
    assert np.allclose(at_samples, surface.reshape(-1), atol=1e-9)
    r, c = 21, 38
    gy, gx = (r + 0.5) / size * (n - 1), (c + 0.5) / size * (n - 1)
    base = surface[::stride, ::stride]
    by, bx = gy / stride, gx / stride
    iy, ix = int(by), int(bx)
    fy, fx = by - iy, bx - ix
    bilinear = (base[iy, ix] * (1 - fx) * (1 - fy) + base[iy, ix + 1] * fx * (1 - fy)
                + base[iy + 1, ix] * (1 - fx) * fy + base[iy + 1, ix + 1] * fx * fy)
    cubic = ndimage.map_coordinates(coeffs, [[gy], [gx]], order=3, mode="nearest", prefilter=False)[0]
    assert res[r, c] == pytest.approx(cubic - bilinear, abs=1e-6)
    with pytest.raises(ValueError):
        displacement_residual(surface, size, base_stride=3)


def test_render_base_stride_caps_the_base_grid_at_257():
    from app.world.textured_terrain import render_base_stride

    for n in (9, 257, 513, 1025):
        stride = render_base_stride(n)
        assert (n - 1) % stride == 0 and (n - 1) // stride + 1 <= 257


def test_glb_export_writes_a_displacement_sidecar_that_round_trips(tmp_path):
    import json

    from PIL import Image

    from app.world.textured_terrain import displacement_residual, render_base_stride, terrain_surface

    out = tmp_path / "vale.glb"
    result = export_textured_terrain_glb(SPEC, out, texture_size=64)
    meta = json.loads((tmp_path / "vale.displacement.json").read_text())
    assert result["displacement"]["resolution"] == 64 and meta["encoding"] == "png16_linear"
    assert meta["kind"] == "terrain_base_grid"
    heights = np.load(tmp_path / meta["base_grid"]["heights_file"])
    assert heights.shape == (meta["base_grid"]["vertices_per_side"],) * 2
    with Image.open(tmp_path / "vale.displacement.png") as im:
        q = np.asarray(im).astype(np.float64)
    decoded = meta["min_m"] + q / 65535.0 * (meta["max_m"] - meta["min_m"])
    _, surface = terrain_surface(SPEC)
    stride = render_base_stride(surface.shape[0])
    assert np.allclose(heights, surface[::stride, ::stride] * SPEC.height_scale_meters, atol=1e-4)
    expected = displacement_residual(surface, 64, base_stride=stride) * SPEC.height_scale_meters
    step = (meta["max_m"] - meta["min_m"]) / 65535.0
    assert np.abs(decoded - expected).max() <= step
    assert meta["max_m"] > 0 > meta["min_m"]  # the cubic surface bulges both ways from the triangles


def test_glb_export_without_displacement_writes_no_sidecar(tmp_path):
    result = export_textured_terrain_glb(SPEC, tmp_path / "flat.glb", texture_size=32, displacement=False)
    assert result["displacement"] is None
    assert not (tmp_path / "flat.displacement.png").exists()


def test_diamond_square_is_deterministic_and_allows_power_12():
    import hashlib

    from app.world.terrain import diamond_square_heightmap

    spec = TerrainSpec(name="d", size_meters=100, height_scale_meters=10, resolution_power=6, seed=5)
    # pinned from the original scalar implementation: vectorizing must not change any seed's terrain
    h = hashlib.sha256(diamond_square_heightmap(spec).tobytes()).hexdigest()
    assert h == '6a22d2a6a34eb5f6535df6cba5a0122fba15dae687bb808218af8a3c008115e3'
    assert TerrainSpec(name="b", size_meters=100, height_scale_meters=10, resolution_power=12).resolution_power == 12
    with pytest.raises(ValueError):
        TerrainSpec(name="b", size_meters=100, height_scale_meters=10, resolution_power=13)
