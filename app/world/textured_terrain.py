from __future__ import annotations

"""Terrain exported as one self-contained, textured PBR glTF: geometry, UVs,
and embedded basecolor / metallic-roughness / normal maps (up to 16K)
synthesized from the same heightmap, so any glTF viewer or engine renders it
fully shaded with no side files.

For offline rendering it also writes a displacement sidecar: the exact
vertical difference between the smooth (cubic B-spline) surface through the
heightmap samples and the flat triangles actually exported. It is zero at
every vertex and carries only the curvature a triangle cannot represent, so
a renderer that subdivides at render time (Cycles adaptive subdivision, see
app/render/cycles_worker.py) gets silhouettes and ridgelines as smooth as
the output resolution demands, with no double counting against the normal
map (which encodes micro-relief relative to that smooth surface).
"""

import json
import tempfile
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image
from scipy import ndimage

import app.qa.textures  # noqa: F401  (raises PIL's pixel guard to cover 16K textures)
from app.core.axes import ZUP_TO_YUP, export_mesh_from_zup
from app.exports.glb_writer import write_textured_glb
from app.world.biome_texture_synthesis import MIN_TEXTURE_SIZE, StreamingPNGWriter, export_biome_texture_maps
from app.world.biomes import BiomeThresholds
from app.world.terrain import TerrainSpec, diamond_square_heightmap, heightmap_to_mesh, terrain_uvs

# Maps are streamed to disk and embedded one at a time, so peak memory while
# encoding is about one decoded image, not the whole set.
MAX_EMBEDDED_TEXTURE_SIZE = 16384
# The residual is smooth (piecewise cubic across heightmap cells); 8 texels
# per cell of the densest terrain (1025^2) resolves it, and a float copy of a
# larger map would cost the renderer gigabytes for no visible gain.
MAX_DISPLACEMENT_SIZE = 8192
DISPLACEMENT_SCHEMA = "character3d-displacement-v1"


def terrain_surface(spec: TerrainSpec, thresholds: BiomeThresholds | None = None, *, flatten_water: bool = True):
    heightmap = diamond_square_heightmap(spec)
    # Terrain below the water level becomes a flat water surface (what the
    # texture paints there); texture depth shading still uses the lakebed.
    water_level = (thresholds or BiomeThresholds()).water_level
    surface = np.maximum(heightmap, water_level) if flatten_water else heightmap
    return heightmap, surface


def displacement_residual(surface: np.ndarray, size: int, *, band_rows: int = 512) -> np.ndarray:
    """(size, size) float32 in the heightmap's normalized height units:
    cubic B-spline surface minus the exported mesh's own linear triangle
    interpolation, sampled at texel centres with the same UV mapping as the
    texture maps (texel row r, col c <-> heightmap coords ((r+0.5)/size,
    (c+0.5)/size) * (n-1)). Triangles follow heightmap_to_mesh's split:
    (r,c),(r,c+1),(r+1,c) and (r,c+1),(r+1,c+1),(r+1,c)."""
    n = surface.shape[0]
    coeffs = ndimage.spline_filter(surface.astype(np.float64), order=3, mode="nearest")
    cols = (np.arange(size) + 0.5) / size * (n - 1)
    out = np.empty((size, size), dtype=np.float32)
    for r0 in range(0, size, band_rows):
        rows = (np.arange(r0, min(size, r0 + band_rows)) + 0.5) / size * (n - 1)
        gy, gx = np.meshgrid(rows, cols, indexing="ij")
        cubic = ndimage.map_coordinates(coeffs, [gy, gx], order=3, mode="nearest", prefilter=False)
        iy = np.minimum(np.floor(gy).astype(np.int64), n - 2)
        ix = np.minimum(np.floor(gx).astype(np.int64), n - 2)
        fy, fx = gy - iy, gx - ix
        h00, h01 = surface[iy, ix], surface[iy, ix + 1]
        h10, h11 = surface[iy + 1, ix], surface[iy + 1, ix + 1]
        linear = np.where(
            fx + fy <= 1.0,
            h00 + fx * (h01 - h00) + fy * (h10 - h00),
            h11 + (1.0 - fx) * (h10 - h11) + (1.0 - fy) * (h01 - h11),
        )
        out[r0:r0 + len(rows)] = cubic - linear
    return out


def write_displacement_sidecar(residual_m: np.ndarray, png_path: Path, json_path: Path) -> dict:
    """16-bit grayscale PNG (linear, exact to (max-min)/65535 m) plus the
    JSON that maps it back to meters."""
    lo, hi = float(residual_m.min()), float(residual_m.max())
    span = hi - lo
    size = residual_m.shape[0]
    writer = StreamingPNGWriter(png_path, size, size, 1, bit_depth=16)
    try:
        for r0 in range(0, size, 1024):
            band = residual_m[r0:r0 + 1024]
            q = np.zeros(band.shape, dtype=np.uint16) if span == 0 else np.round((band - lo) / span * 65535.0).astype(np.uint16)
            writer.write_rows(q)
        writer.close()
    except BaseException:
        writer.abort()
        raise
    meta = {
        "schema": DISPLACEMENT_SCHEMA,
        "image": png_path.name,
        "encoding": "png16_linear",
        "min_m": lo,
        "max_m": hi,
        "resolution": size,
        "uv_set": 0,
        "kind": "vertical_residual_to_exported_mesh",
        "note": "height = min_m + (value/65535)*(max_m-min_m) meters along the up axis; zero at every mesh vertex.",
    }
    json_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def displacement_sidecar_paths(glb_path: str | Path) -> tuple[Path, Path]:
    p = Path(glb_path)
    return p.with_name(p.stem + ".displacement.png"), p.with_name(p.stem + ".displacement.json")


def _build(spec, *, texture_size, thresholds, flatten_water, maps_dir: Path, load_into_memory: bool) -> trimesh.Trimesh:
    if not MIN_TEXTURE_SIZE <= texture_size <= MAX_EMBEDDED_TEXTURE_SIZE:
        raise ValueError(f"texture_size must be between {MIN_TEXTURE_SIZE} and {MAX_EMBEDDED_TEXTURE_SIZE} for an embedded-texture GLB")
    heightmap, surface = terrain_surface(spec, thresholds, flatten_water=flatten_water)
    mesh = heightmap_to_mesh(surface, size_meters=spec.size_meters, height_scale_meters=spec.height_scale_meters)
    paths = export_biome_texture_maps(
        heightmap, texture_size=texture_size, seed=spec.seed, thresholds=thresholds,
        basecolor_path=maps_dir / "basecolor.png", roughness_path=maps_dir / "roughness.png",
        normal_path=maps_dir / "normal.png", metallic_roughness_path=maps_dir / "metallic_roughness.png",
    )

    def image(key):
        img = Image.open(paths[key])
        if load_into_memory:
            img.load()
        return img

    material = trimesh.visual.material.PBRMaterial(
        name=f"{spec.name}_terrain",
        baseColorTexture=image("basecolor_path"),
        metallicRoughnessTexture=image("metallic_roughness_path"),
        normalTexture=image("normal_path"),
        metallicFactor=0.0,
        roughnessFactor=1.0,
    )
    mesh.visual = trimesh.visual.TextureVisuals(uv=terrain_uvs(heightmap.shape[0]), material=material)
    return mesh


def _write_glb_streaming(spec, out: Path, *, texture_size, thresholds, flatten_water, maps_dir: Path) -> tuple[int, int]:
    """Maps stream to PNG files, then the GLB streams those bytes in
    unchanged (app/exports/glb_writer.py): memory stays at about the
    geometry, never a decoded 16K image."""
    heightmap, surface = terrain_surface(spec, thresholds, flatten_water=flatten_water)
    mesh = heightmap_to_mesh(surface, size_meters=spec.size_meters, height_scale_meters=spec.height_scale_meters)
    paths = export_biome_texture_maps(
        heightmap, texture_size=texture_size, seed=spec.seed, thresholds=thresholds,
        basecolor_path=maps_dir / "basecolor.png", roughness_path=maps_dir / "roughness.png",
        normal_path=maps_dir / "normal.png", metallic_roughness_path=maps_dir / "metallic_roughness.png",
    )
    rot = ZUP_TO_YUP[:3, :3].T  # to glTF's Y-up
    uv = terrain_uvs(heightmap.shape[0])
    uv_gltf = np.stack([uv[:, 0], 1.0 - uv[:, 1]], axis=1)  # glTF UV origin is top-left
    write_textured_glb(
        out,
        positions=mesh.vertices @ rot, normals=mesh.vertex_normals @ rot, texcoords=uv_gltf, indices=mesh.faces,
        base_color_png=paths["basecolor_path"], normal_png=paths["normal_path"],
        metallic_roughness_png=paths["metallic_roughness_path"],
        material_name=f"{spec.name}_terrain", mesh_name=spec.name,
    )
    return len(mesh.vertices), len(mesh.faces)


def build_textured_terrain(
    spec: TerrainSpec,
    *,
    texture_size: int,
    thresholds: BiomeThresholds | None = None,
    flatten_water: bool = True,
) -> trimesh.Trimesh:
    """In-memory textured mesh (maps fully decoded). For large texture sizes
    use export_textured_terrain_glb, which keeps memory bounded."""
    with tempfile.TemporaryDirectory() as d:
        return _build(spec, texture_size=texture_size, thresholds=thresholds, flatten_water=flatten_water,
                      maps_dir=Path(d), load_into_memory=True)


def export_textured_terrain_glb(
    spec: TerrainSpec,
    output_path: str | Path,
    *,
    texture_size: int,
    thresholds: BiomeThresholds | None = None,
    flatten_water: bool = True,
    displacement: bool = True,
) -> dict:
    """Write the textured GLB (and, by default, its displacement sidecar).
    Returns counts and paths; embedded images are streamed from temporary
    files, so the mesh is not kept."""
    out = Path(output_path)
    if out.suffix.lower() not in (".glb", ".gltf"):
        raise ValueError("textured terrain output must be .glb or .gltf")
    if not MIN_TEXTURE_SIZE <= texture_size <= MAX_EMBEDDED_TEXTURE_SIZE:
        raise ValueError(f"texture_size must be between {MIN_TEXTURE_SIZE} and {MAX_EMBEDDED_TEXTURE_SIZE} for an embedded-texture GLB")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent) as d:
        if out.suffix.lower() == ".gltf":
            mesh = _build(spec, texture_size=texture_size, thresholds=thresholds, flatten_water=flatten_water,
                          maps_dir=Path(d), load_into_memory=False)
            export_mesh_from_zup(mesh, out)
            counts = len(mesh.vertices), len(mesh.faces)
            del mesh
        else:
            counts = _write_glb_streaming(spec, out, texture_size=texture_size, thresholds=thresholds,
                                          flatten_water=flatten_water, maps_dir=Path(d))
        result = {"output_path": str(out), "vertex_count": counts[0], "face_count": counts[1],
                  "texture_size": texture_size, "displacement": None}

    if displacement:
        _, surface = terrain_surface(spec, thresholds, flatten_water=flatten_water)
        size = min(texture_size, MAX_DISPLACEMENT_SIZE)
        residual_m = displacement_residual(surface, size) * np.float32(spec.height_scale_meters)
        png_path, json_path = displacement_sidecar_paths(out)
        meta = write_displacement_sidecar(residual_m, png_path, json_path)
        result["displacement"] = {"image_path": str(png_path), "metadata_path": str(json_path),
                                  "min_m": meta["min_m"], "max_m": meta["max_m"], "resolution": size}
    return result
