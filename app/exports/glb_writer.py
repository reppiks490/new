from __future__ import annotations

"""Streaming GLB writer for one textured, PBR-material mesh.

Embeds already-encoded PNG files byte-for-byte, streaming them into the BIN
chunk, so writing a GLB with three 16K textures needs about as much memory
as the geometry arrays -- the general-purpose exporter decodes, copies and
re-encodes every image (measured: 11.5 GB peak at 16K). Follows the glTF 2.0
binary container spec: 12-byte header, JSON chunk padded with spaces, BIN
chunk padded with zeros, every buffer view 4-byte aligned.
"""

import json
import struct
from pathlib import Path

import numpy as np

GLB_MAGIC = 0x46546C67
JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942
FLOAT, UINT32 = 5126, 5125
ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER = 34962, 34963
LINEAR, LINEAR_MIPMAP_LINEAR, CLAMP_TO_EDGE = 9729, 9987, 33071


def _pad4(n: int) -> int:
    return (4 - n % 4) % 4


def write_textured_glb(
    path: str | Path,
    *,
    positions: np.ndarray,
    normals: np.ndarray,
    texcoords: np.ndarray,
    indices: np.ndarray,
    base_color_png: str | Path,
    metallic_roughness_png: str | Path | None = None,
    normal_png: str | Path | None = None,
    material_name: str = "material",
    metallic_factor: float = 0.0,
    roughness_factor: float = 1.0,
    mesh_name: str = "mesh",
) -> Path:
    """positions/normals (N,3) and texcoords (N,2) must already be in glTF
    conventions (Y-up; UV origin top-left); indices (M,3) index them."""
    positions = np.ascontiguousarray(positions, dtype="<f4")
    normals = np.ascontiguousarray(normals, dtype="<f4")
    texcoords = np.ascontiguousarray(texcoords, dtype="<f4")
    indices = np.ascontiguousarray(indices, dtype="<u4")
    n = len(positions)
    if positions.shape != (n, 3) or normals.shape != (n, 3) or texcoords.shape != (n, 2):
        raise ValueError("positions/normals must be (N,3) and texcoords (N,2)")
    if indices.ndim != 2 or indices.shape[1] != 3 or (len(indices) and int(indices.max()) >= n):
        raise ValueError("indices must be (M,3) and within range")
    if not np.isfinite(positions).all():
        raise ValueError("positions contain non-finite values")

    images = [("baseColor", Path(base_color_png))]
    if normal_png is not None:
        images.append(("normal", Path(normal_png)))
    if metallic_roughness_png is not None:
        images.append(("metallicRoughness", Path(metallic_roughness_png)))
    for _, p in images:
        with open(p, "rb") as fh:
            if fh.read(8) != b"\x89PNG\r\n\x1a\n":
                raise ValueError(f"{p} is not a PNG")

    # (payload, target, byte length); payload is an array or a PNG path
    parts: list[tuple[object, int | None, int]] = [
        (positions, ARRAY_BUFFER, positions.nbytes),
        (normals, ARRAY_BUFFER, normals.nbytes),
        (texcoords, ARRAY_BUFFER, texcoords.nbytes),
        (indices, ELEMENT_ARRAY_BUFFER, indices.nbytes),
    ] + [(p, None, p.stat().st_size) for _, p in images]
    views, offset = [], 0
    for _, target, length in parts:
        view = {"buffer": 0, "byteOffset": offset, "byteLength": length}
        if target is not None:
            view["target"] = target
        views.append(view)
        offset += length + _pad4(length)
    bin_length = offset

    texture_index = {role: i for i, (role, _) in enumerate(images)}
    pbr = {"baseColorTexture": {"index": texture_index["baseColor"]},
           "metallicFactor": float(metallic_factor), "roughnessFactor": float(roughness_factor)}
    if "metallicRoughness" in texture_index:
        pbr["metallicRoughnessTexture"] = {"index": texture_index["metallicRoughness"]}
    material = {"name": material_name, "pbrMetallicRoughness": pbr}
    if "normal" in texture_index:
        material["normalTexture"] = {"index": texture_index["normal"]}

    gltf = {
        "asset": {"version": "2.0", "generator": "character3d-masterbuild glb_writer"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": mesh_name}],
        "meshes": [{"name": mesh_name, "primitives": [{
            "attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2},
            "indices": 3, "material": 0, "mode": 4,
        }]}],
        "materials": [material],
        "samplers": [{"magFilter": LINEAR, "minFilter": LINEAR_MIPMAP_LINEAR, "wrapS": CLAMP_TO_EDGE, "wrapT": CLAMP_TO_EDGE}],
        "textures": [{"sampler": 0, "source": i} for i in range(len(images))],
        "images": [{"bufferView": 4 + i, "mimeType": "image/png", "name": role} for i, (role, _) in enumerate(images)],
        "accessors": [
            {"bufferView": 0, "componentType": FLOAT, "count": n, "type": "VEC3",
             "min": positions.min(axis=0).tolist(), "max": positions.max(axis=0).tolist()},
            {"bufferView": 1, "componentType": FLOAT, "count": n, "type": "VEC3"},
            {"bufferView": 2, "componentType": FLOAT, "count": n, "type": "VEC2"},
            {"bufferView": 3, "componentType": UINT32, "count": int(indices.size), "type": "SCALAR"},
        ],
        "bufferViews": views,
        "buffers": [{"byteLength": bin_length}],
    }
    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * _pad4(len(json_bytes))
    total = 12 + 8 + len(json_bytes) + 8 + bin_length

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as fh:
        fh.write(struct.pack("<III", GLB_MAGIC, 2, total))
        fh.write(struct.pack("<II", len(json_bytes), JSON_CHUNK))
        fh.write(json_bytes)
        fh.write(struct.pack("<II", bin_length, BIN_CHUNK))
        for payload, _, length in parts:
            if isinstance(payload, np.ndarray):
                fh.write(payload.tobytes())
            else:
                with open(payload, "rb") as src:
                    while chunk := src.read(16 * 1024 * 1024):
                        fh.write(chunk)
            fh.write(b"\x00" * _pad4(length))
    return out
