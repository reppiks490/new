import sys
from pathlib import Path

from app.exports.gltf_validation import _load_glb
from app.render.cycles_worker import texel_limited_subdivisions
from app.world.terrain import TerrainSpec
from app.world.textured_terrain import export_textured_terrain_glb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender_scripts"))
from glb_proxy import read_glb_json, write_terrain_proxy  # noqa: E402


def test_proxy_keeps_materials_and_image_bytes_but_drops_the_dense_geometry(tmp_path):
    src = tmp_path / "t.glb"
    export_textured_terrain_glb(TerrainSpec(name="t", size_meters=80, resolution_power=6, height_scale_meters=20),
                                src, texture_size=64, displacement=False)
    stats = write_terrain_proxy(src, tmp_path / "p.glb")
    assert stats["source_triangles"] == 2 * 64 * 64
    a, a_bin = read_glb_json(src)
    b, b_bin = read_glb_json(tmp_path / "p.glb")
    assert b["materials"] == a["materials"] and b["textures"] == a["textures"] and len(b["images"]) == len(a["images"])
    src_bytes, dst_bytes = src.read_bytes(), (tmp_path / "p.glb").read_bytes()
    for ia, ib in zip(a["images"], b["images"]):
        va, vb = a["bufferViews"][ia["bufferView"]], b["bufferViews"][ib["bufferView"]]
        assert src_bytes[a_bin + va["byteOffset"]:][:va["byteLength"]] == dst_bytes[b_bin + vb["byteOffset"]:][:vb["byteLength"]]
    pos = b["accessors"][b["meshes"][0]["primitives"][0]["attributes"]["POSITION"]]
    orig = a["accessors"][a["meshes"][0]["primitives"][0]["attributes"]["POSITION"]]
    assert pos["count"] == 4 and pos["min"][0] == orig["min"][0] and pos["max"][2] == orig["max"][2]
    _load_glb(tmp_path / "p.glb")  # structurally valid GLB


def test_subdivision_cap_follows_displacement_texel_density():
    disp = {"resolution": 8192, "base_grid": {"vertices_per_side": 257}}
    assert texel_limited_subdivisions(disp) == 6  # 32 texels per base quad -> 64 cuts
    assert texel_limited_subdivisions({"resolution": 256, "base_grid": {"vertices_per_side": 257}}) == 1
    assert texel_limited_subdivisions(None) == 12
