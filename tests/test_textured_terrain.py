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


@pytest.mark.parametrize("size", [4, 8193])
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
