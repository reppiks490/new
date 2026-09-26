from __future__ import annotations

"""Terrain exported as one self-contained, textured PBR glTF: geometry, UVs,
and embedded basecolor / metallic-roughness / normal maps synthesized from
the same heightmap, so any glTF viewer or engine renders it fully shaded
with no side files."""

from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

from app.core.axes import export_mesh_from_zup
from app.world.biome_texture_synthesis import synthesize_biome_texture_maps
from app.world.biomes import BiomeThresholds
from app.world.terrain import TerrainSpec, diamond_square_heightmap, heightmap_to_mesh, terrain_uvs

# Embedded textures are held in memory while the GLB is encoded (unlike the
# standalone PNG export, which streams), so the in-GLB ceiling is 8K.
MAX_EMBEDDED_TEXTURE_SIZE = 8192


def build_textured_terrain(
    spec: TerrainSpec,
    *,
    texture_size: int,
    thresholds: BiomeThresholds | None = None,
) -> trimesh.Trimesh:
    if not 8 <= texture_size <= MAX_EMBEDDED_TEXTURE_SIZE:
        raise ValueError(f"texture_size must be between 8 and {MAX_EMBEDDED_TEXTURE_SIZE} for an embedded-texture GLB")
    heightmap = diamond_square_heightmap(spec)
    mesh = heightmap_to_mesh(heightmap, size_meters=spec.size_meters, height_scale_meters=spec.height_scale_meters)
    maps = synthesize_biome_texture_maps(heightmap, texture_size=texture_size, seed=spec.seed, thresholds=thresholds)

    # glTF metallicRoughness: G = roughness, B = metallic (terrain is fully
    # dielectric), R unused by the spec -- left at 255.
    roughness = maps["roughness"]
    metallic_roughness = np.stack(
        [np.full_like(roughness, 255), roughness, np.zeros_like(roughness)], axis=-1
    )
    material = trimesh.visual.material.PBRMaterial(
        name=f"{spec.name}_terrain",
        baseColorTexture=Image.fromarray(maps["basecolor"], mode="RGB"),
        metallicRoughnessTexture=Image.fromarray(metallic_roughness, mode="RGB"),
        normalTexture=Image.fromarray(maps["normal"], mode="RGB"),
        metallicFactor=0.0,
        roughnessFactor=1.0,
    )
    mesh.visual = trimesh.visual.TextureVisuals(uv=terrain_uvs(heightmap.shape[0]), material=material)
    return mesh


def export_textured_terrain_glb(
    spec: TerrainSpec,
    output_path: str | Path,
    *,
    texture_size: int,
    thresholds: BiomeThresholds | None = None,
) -> trimesh.Trimesh:
    out = Path(output_path)
    if out.suffix.lower() not in (".glb", ".gltf"):
        raise ValueError("textured terrain output must be .glb or .gltf")
    mesh = build_textured_terrain(spec, texture_size=texture_size, thresholds=thresholds)
    out.parent.mkdir(parents=True, exist_ok=True)
    export_mesh_from_zup(mesh, out)
    return mesh
