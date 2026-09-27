"""Blender selected-to-active UDIM bake worker (Blender 4.x/5.x).

Bakes NORMAL (tangent space, glTF/OpenGL +Y) and AO from high-poly source
meshes onto a UV'd low-poly target. Displacement/curvature/thickness are
reported as unexecuted: Cycles has no native high->low bake for them.

What makes the receipt trustworthy rather than a formality:
- Ray reach comes from the real geometry. The signed distance of the
  high-poly surface from the low-poly surface is measured with a BVH, and
  cage extrusion / max ray distance are derived from it (unless the
  contract pins them). A fixed guess silently misses: Blender writes a flat
  normal and black AO wherever a ray finds nothing.
- A hit-mask bake (EMIT from a white high-poly, margin 0) measures the
  fraction of UV-covered texels whose rays actually hit, per UDIM tile.
- Which UDIM tiles the low-poly UVs occupy is computed from the mesh, and
  every file path in the receipt is a real file checked on disk.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import traceback
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

NATIVE_BAKE_TYPES = {'normal': 'NORMAL', 'ambient_occlusion': 'AO'}
DEVIATION_SAMPLE_LIMIT = 200_000
MASK_RESOLUTION = 1024


def args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument('--contract', required=True)
    p.add_argument('--workspace', required=True)
    return p.parse_args(argv)


def _start_clean_scene():
    # Blender's startup scene carries a default cube/camera/light that would
    # otherwise be baked alongside the real asset. A .blend passed on the
    # command line is the intended scene and is kept.
    if not bpy.data.filepath:
        bpy.ops.wm.read_factory_settings(use_empty=True)


def import_model(path: Path, prefix: str):
    before = set(bpy.data.objects)
    ext = path.suffix.lower()
    if ext in {'.glb', '.gltf'}:
        bpy.ops.import_scene.gltf(filepath=str(path))
    elif ext == '.fbx':
        bpy.ops.import_scene.fbx(filepath=str(path))
    elif ext == '.obj':
        bpy.ops.wm.obj_import(filepath=str(path))
    else:
        raise RuntimeError(f'unsupported bake source: {ext}')
    created = [o for o in bpy.data.objects if o not in before and o.type == 'MESH']
    if not created:
        raise RuntimeError(f'no mesh objects imported from {path}')
    for i, o in enumerate(created):
        o.name = f'{prefix}_{i:03d}'
    return created


def join_meshes(objects, name: str):
    if len(objects) == 1:
        objects[0].name = name
        return objects[0]
    bpy.ops.object.select_all(action='DESELECT')
    for o in objects:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.join()
    joined = bpy.context.view_layer.objects.active
    joined.name = name
    return joined


def _world_verts(obj) -> np.ndarray:
    mesh = obj.data
    co = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
    mesh.vertices.foreach_get('co', co)
    co = co.reshape(-1, 3)
    m = np.array(obj.matrix_world)
    return co @ m[:3, :3].T + m[:3, 3]


def measure_deviation(highs, low) -> dict:
    """Signed distance of high-poly vertices from the low-poly surface,
    positive along the low surface normal (outside)."""
    low_verts = _world_verts(low)
    polys = [tuple(p.vertices) for p in low.data.polygons]
    bvh = BVHTree.FromPolygons([Vector(v) for v in low_verts], polys)
    high_points = np.concatenate([_world_verts(h) for h in highs])
    stride = max(1, len(high_points) // DEVIATION_SAMPLE_LIMIT)
    signed = []
    for point in high_points[::stride]:
        location, normal, _index, _dist = bvh.find_nearest(Vector(point))
        if location is None:
            continue
        signed.append((Vector(point) - location).dot(normal))
    signed = np.asarray(signed)
    diagonal = float(np.linalg.norm(low_verts.max(0) - low_verts.min(0)))
    return {
        'samples': int(len(signed)),
        'outward_max': float(max(signed.max(), 0.0)),
        'inward_max': float(max(-signed.min(), 0.0)),
        'outward_p999': float(max(np.percentile(signed, 99.9), 0.0)),
        'inward_p999': float(max(-np.percentile(signed, 0.1), 0.0)),
        'low_diagonal': diagonal,
    }


def choose_ray_settings(contract: dict, deviation: dict) -> dict:
    # 99.9th percentile rather than max: a few stray high-poly verts far off
    # the surface would otherwise inflate reach enough to hit neighbouring
    # geometry (finger onto finger). The hit mask reports whatever misses.
    eps = deviation['low_diagonal'] * 1e-4
    extrusion = contract.get('cage_extrusion')
    auto_extrusion = extrusion is None
    if auto_extrusion:
        extrusion = deviation['outward_p999'] * 1.05 + eps
    max_ray = contract.get('ray_distance')
    auto_ray = max_ray is None
    if auto_ray:
        max_ray = extrusion + deviation['inward_p999'] * 1.05 + eps
    return {'cage_extrusion': float(extrusion), 'max_ray_distance': float(max_ray),
            'auto_cage_extrusion': auto_extrusion, 'auto_ray_distance': auto_ray}


def uv_tile_coverage(low) -> list[int]:
    mesh = low.data
    if not mesh.uv_layers:
        raise RuntimeError('low mesh has no UV layer')
    uv = np.empty(len(mesh.loops) * 2, dtype=np.float64)
    mesh.uv_layers.active.data.foreach_get('uv', uv)
    uv = uv.reshape(-1, 2)
    starts = np.empty(len(mesh.polygons), dtype=np.int64)
    counts = np.empty(len(mesh.polygons), dtype=np.int64)
    mesh.polygons.foreach_get('loop_start', starts)
    mesh.polygons.foreach_get('loop_total', counts)
    centroids = np.add.reduceat(uv, starts, axis=0) / counts[:, None]
    tiles = 1001 + np.floor(centroids[:, 0]).astype(int) + 10 * np.floor(centroids[:, 1]).astype(int)
    return sorted(int(t) for t in np.unique(tiles))


def _material_slots(low):
    if not low.data.materials:
        low.data.materials.append(bpy.data.materials.new(name=f'{low.name}_BAKE'))
    mats = []
    for i, mat in enumerate(low.data.materials):
        if mat is None:
            mat = bpy.data.materials.new(name=f'{low.name}_BAKE_{i}')
            low.data.materials[i] = mat
        if mat.node_tree is None:
            mat.use_nodes = True
        mats.append(mat)
    return mats


def new_tiled_image(name, resolution, tiles, *, float_buffer, fill):
    img = bpy.data.images.new(name, width=resolution, height=resolution, tiled=True, float_buffer=float_buffer, alpha=True)
    img.colorspace_settings.name = 'Non-Color'
    for tile in tiles:
        if tile not in {t.number for t in img.tiles}:
            img.tiles.new(tile_number=tile)
    # tiles.new() allocates no pixel buffer (baking into it fails with
    # "Uninitialized image"), and UDIMTile.generated_color alone fills
    # nothing -- verified against Blender 5.0. tile_fill does both; it reads
    # the image from the context, so hand it over explicitly (no image
    # editor exists in background mode).
    for t in img.tiles:
        img.tiles.active = t
        with bpy.context.temp_override(edit_image=img):
            bpy.ops.image.tile_fill(color=fill, generated_type='BLANK', width=resolution, height=resolution,
                                    float=float_buffer, alpha=True)
    return img


def set_bake_target(low, image):
    # Every material slot needs the active image node, or Cycles refuses to
    # bake faces that use the other slots.
    for mat in _material_slots(low):
        nodes = mat.node_tree.nodes
        node = nodes.get('CHARACTER3D_BAKE_TARGET') or nodes.new('ShaderNodeTexImage')
        node.name = 'CHARACTER3D_BAKE_TARGET'
        node.image = image
        node.interpolation = 'Linear'
        nodes.active = node


def select_for_bake(highs, low):
    bpy.ops.object.select_all(action='DESELECT')
    for o in highs:
        o.select_set(True)
    low.select_set(True)
    bpy.context.view_layer.objects.active = low


def save_tiles(image, directory: Path, stem: str, tiles) -> dict[int, str]:
    directory.mkdir(parents=True, exist_ok=True)
    image.filepath_raw = str(directory / f'{stem}.<UDIM>.exr')
    image.file_format = 'OPEN_EXR'
    image.save()
    written = {}
    for tile in tiles:
        path = directory / f'{stem}.{tile}.exr'
        if path.is_file() and path.stat().st_size > 0:
            written[int(tile)] = str(path)
    return written


def hit_mask_stats(highs, low, tiles, workspace: Path, ray: dict) -> dict:
    white = bpy.data.materials.new('CHARACTER3D_HIT_MASK')
    nt = white.node_tree
    nt.nodes.clear()
    emission = nt.nodes.new('ShaderNodeEmission')
    emission.inputs['Color'].default_value = (1, 1, 1, 1)
    emission.inputs['Strength'].default_value = 1.0
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    nt.links.new(emission.outputs[0], out.inputs[0])
    saved = {h.name: [s.material for s in h.material_slots] for h in highs}
    for h in highs:
        h.data.materials.clear()
        h.data.materials.append(white)

    sentinel = (0.25, 0.5, 0.75, 0.5)
    mask = new_tiled_image('CHARACTER3D_HIT_MASK', MASK_RESOLUTION, tiles, float_buffer=True, fill=sentinel)
    set_bake_target(low, mask)
    scene = bpy.context.scene
    scene.cycles.samples = 1
    bake = scene.render.bake
    previous_margin = bake.margin
    bake.margin = 0
    select_for_bake(highs, low)
    bpy.ops.object.bake(type='EMIT')
    bake.margin = previous_margin
    files = save_tiles(mask, workspace / 'bakes' / '_qa', 'hit_mask', tiles)

    for h in highs:
        h.data.materials.clear()
        for m in saved[h.name]:
            h.data.materials.append(m)

    per_tile = {}
    total_hit = total_miss = 0
    for tile, path in files.items():
        img = bpy.data.images.load(path)
        px = np.array(img.pixels[:], dtype=np.float32).reshape(-1, 4)
        bpy.data.images.remove(img)
        untouched = np.isclose(px[:, 3], sentinel[3], atol=1e-3)
        hit = (~untouched) & (px[:, 3] > 0.5)
        miss = (~untouched) & (px[:, 3] <= 0.5)
        h, m = int(hit.sum()), int(miss.sum())
        total_hit += h
        total_miss += m
        per_tile[tile] = {'hit_texels': h, 'miss_texels': m,
                          'miss_fraction': (m / (h + m)) if (h + m) else None}
    covered = total_hit + total_miss
    return {'resolution': MASK_RESOLUTION, 'per_tile': per_tile,
            'miss_fraction': (total_miss / covered) if covered else None}


def bake_channel(highs, low, channel: dict, contract: dict, workspace: Path, ray: dict) -> dict:
    name = channel['name']
    bake_type = NATIVE_BAKE_TYPES.get(name)
    if not bake_type:
        return {'channel': name, 'executed': False,
                'reason': 'no native Cycles high->low bake for this channel; requires an explicit source binding'}
    tiles = list(contract['udim_tiles'])
    float_buffer = int(channel['bit_depth']) > 8
    image = new_tiled_image(f'CHARACTER3D_{name}', int(contract['resolution']), tiles,
                            float_buffer=float_buffer, fill=(0.5, 0.5, 1.0, 1.0) if name == 'normal' else (1, 1, 1, 1))
    set_bake_target(low, image)
    scene = bpy.context.scene
    scene.cycles.samples = 1 if name == 'normal' else int(contract.get('bake_samples', 64))
    bake = scene.render.bake
    bake.margin = int(contract['margin_px'])
    if name == 'normal':
        bake.normal_space = 'TANGENT'
        bake.normal_r, bake.normal_g, bake.normal_b = 'POS_X', 'POS_Y', 'POS_Z'
    select_for_bake(highs, low)
    bpy.ops.object.bake(type=bake_type)
    written = save_tiles(image, workspace / 'bakes', name, tiles)
    return {'channel': name, 'executed': True, 'tile_filepaths': {str(k): v for k, v in written.items()},
            'bit_depth': 32 if float_buffer else 8, 'samples': scene.cycles.samples}


def main():
    a = args()
    contract = json.loads(Path(a.contract).read_text())
    workspace = Path(a.workspace)
    receipt = {'schema': 'character3d-high-low-bake-receipt-v2', 'status': 'running', 'channels': [],
               'blender_version': bpy.app.version_string}
    _start_clean_scene()
    out = workspace / 'high_low_bake_receipt.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        if contract.get('blockers'):
            raise RuntimeError('bake contract has blockers: ' + '; '.join(contract['blockers']))
        src = contract['source']
        highs = import_model(Path(src['high_mesh']), 'HIGH')
        low = join_meshes(import_model(Path(src['low_mesh']), 'LOW'), 'LOW')
        if src.get('cage_mesh'):
            cage = join_meshes(import_model(Path(src['cage_mesh']), 'CAGE'), 'CAGE')
            bpy.context.scene.render.bake.use_cage = True
            bpy.context.scene.render.bake.cage_object = cage

        scene = bpy.context.scene
        scene.render.engine = 'CYCLES'
        scene.render.bake.use_selected_to_active = True
        deviation = measure_deviation(highs, low)
        ray = choose_ray_settings(contract, deviation)
        scene.render.bake.cage_extrusion = ray['cage_extrusion']
        scene.render.bake.max_ray_distance = ray['max_ray_distance']
        if scene.world is None:
            scene.world = bpy.data.worlds.new('BakeWorld')
        ao_distance = contract.get('ao_distance') or deviation['low_diagonal'] * 0.1
        scene.world.light_settings.distance = ao_distance
        receipt['deviation'] = deviation
        receipt['ray'] = ray
        receipt['ao_distance'] = ao_distance

        tiles = list(contract['udim_tiles'])
        covered = uv_tile_coverage(low)
        receipt['uv_tiles'] = covered
        receipt['uncovered_contract_tiles'] = [t for t in tiles if t not in covered]
        receipt['uv_outside_contract_tiles'] = [t for t in covered if t not in tiles]
        receipt['hit_mask'] = hit_mask_stats(highs, low, tiles, workspace, ray)

        for ch in contract['channels']:
            receipt['channels'].append(bake_channel(highs, low, ch, contract, workspace, ray))
        receipt['status'] = 'succeeded'
    except Exception as exc:
        receipt['status'] = 'failed'
        receipt['error'] = str(exc)
        receipt['traceback'] = traceback.format_exc()
        raise
    finally:
        out.write_text(json.dumps(receipt, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
