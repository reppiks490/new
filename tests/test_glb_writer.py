import json
import struct

import numpy as np
import pytest
from PIL import Image

from app.exports.glb_writer import write_textured_glb
from app.exports.gltf_validation import _load_glb, read_glb_accessor, validate_gltf_structure


def _png(path, color):
    Image.new("RGB", (8, 8), color).save(path)
    return path


def _quad():
    positions = np.array([[0, 0, 0], [1, 0, 0], [0, 0, -1], [1, 0, -1]], float)
    normals = np.tile([0, 1, 0], (4, 1)).astype(float)
    uv = np.array([[0, 1], [1, 1], [0, 0], [1, 0]], float)
    return positions, normals, uv, np.array([[0, 1, 2], [1, 3, 2]])


def test_writes_a_valid_self_contained_glb_with_images_embedded_byte_for_byte(tmp_path):
    p, n, uv, idx = _quad()
    base, nrm, mr = _png(tmp_path / "b.png", (200, 10, 10)), _png(tmp_path / "n.png", (128, 128, 255)), _png(tmp_path / "m.png", (255, 128, 0))
    out = write_textured_glb(tmp_path / "q.glb", positions=p, normals=n, texcoords=uv, indices=idx,
                             base_color_png=base, normal_png=nrm, metallic_roughness_png=mr)
    report = validate_gltf_structure(out)
    assert report.passed and report.image_count == 3 and report.external_resource_count == 0
    gltf, binary = _load_glb(out)
    assert len(binary) % 4 == 0 and all(v["byteOffset"] % 4 == 0 for v in gltf["bufferViews"])
    for image in gltf["images"]:
        view = gltf["bufferViews"][image["bufferView"]]
        src = {"baseColor": base, "normal": nrm, "metallicRoughness": mr}[image["name"]]
        assert binary[view["byteOffset"]:view["byteOffset"] + view["byteLength"]] == src.read_bytes()
    mat = gltf["materials"][0]
    assert gltf["images"][mat["normalTexture"]["index"]]["name"] == "normal"
    assert gltf["images"][mat["pbrMetallicRoughness"]["metallicRoughnessTexture"]["index"]]["name"] == "metallicRoughness"
    assert np.allclose(read_glb_accessor(out, 0), p) and np.allclose(read_glb_accessor(out, 2), uv)
    assert read_glb_accessor(out, 3).tolist() == idx.reshape(-1).tolist()
    header = struct.unpack("<III", out.read_bytes()[:12])
    assert header == (0x46546C67, 2, out.stat().st_size)


def test_trimesh_reads_it_back(tmp_path):
    import trimesh

    p, n, uv, idx = _quad()
    out = write_textured_glb(tmp_path / "q.glb", positions=p, normals=n, texcoords=uv, indices=idx,
                             base_color_png=_png(tmp_path / "b.png", (1, 2, 3)))
    mesh = trimesh.load(out, force="mesh")
    assert len(mesh.faces) == 2


@pytest.mark.parametrize("bad", ["indices", "nan", "notpng"])
def test_rejects_invalid_input(tmp_path, bad):
    p, n, uv, idx = _quad()
    base = _png(tmp_path / "b.png", (1, 2, 3))
    if bad == "indices":
        idx = np.array([[0, 1, 9]])
    elif bad == "nan":
        p = p.copy(); p[0, 0] = np.nan
    else:
        base = tmp_path / "x.png"; base.write_bytes(b"not a png")
    with pytest.raises(ValueError):
        write_textured_glb(tmp_path / "q.glb", positions=p, normals=n, texcoords=uv, indices=idx, base_color_png=base)
