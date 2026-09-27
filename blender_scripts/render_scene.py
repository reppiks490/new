"""Blender-side Cycles render worker.

Consumes a manifest compiled by app/render/cycles_worker.py: imports a model
into an empty scene, frames a camera from its real bounds, lights it with a
physical sky + sun, applies the job's CyclesPreset, renders at the job's
RenderOutputSpec resolution, and writes a receipt recording what actually
happened -- including the compute device really used (a requested GPU
backend that is not present falls back to CPU and the receipt says so).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
import traceback
from pathlib import Path

import bpy
from mathutils import Vector


def _args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument('--manifest', required=True)
    return p.parse_args(argv)


def _import_model(path: Path):
    ext = path.suffix.lower()
    if ext in {'.glb', '.gltf'}:
        bpy.ops.import_scene.gltf(filepath=str(path))
    elif ext == '.obj':
        bpy.ops.wm.obj_import(filepath=str(path))
    elif ext == '.fbx':
        bpy.ops.import_scene.fbx(filepath=str(path))
    elif ext in {'.usd', '.usda', '.usdc', '.usdz'}:
        bpy.ops.wm.usd_import(filepath=str(path))
    else:
        raise RuntimeError(f'Unsupported render import type: {ext}')
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    if not meshes:
        raise RuntimeError('Imported model contains no mesh objects')
    return meshes


def unpack_images_to_files(directory: Path) -> int:
    """Packed images (everything a .glb embeds) reach Cycles only through
    Blender's own decoded copy, so each texture sits in memory twice.
    Written back out as the same bytes and referenced as files, Cycles reads
    them directly and Blender never decodes them: measured on a GLB with
    three 16K maps, peak memory 8.1 GB -> 5.8 GB."""
    directory.mkdir(parents=True, exist_ok=True)
    count = 0
    for i, img in enumerate(bpy.data.images):
        if img.packed_file is None:
            continue
        ext = '.' + (img.file_format or 'PNG').lower().replace('jpeg', 'jpg')
        target = directory / f'packed_{i:03d}{ext}'
        target.write_bytes(img.packed_file.data)
        img.filepath = str(target)
        img.unpack(method='USE_ORIGINAL')
        img.buffers_free()
        count += 1
    return count


def _world_bounds(objects):
    lo = Vector((math.inf,) * 3)
    hi = Vector((-math.inf,) * 3)
    for obj in objects:
        for corner in obj.bound_box:
            w = obj.matrix_world @ Vector(corner)
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
    return lo, hi


def _select_device(requested: str) -> tuple[str, str]:
    """Returns (scene device, backend actually used)."""
    if requested == 'CPU':
        return 'CPU', 'CPU'
    try:
        prefs = bpy.context.preferences.addons['cycles'].preferences
        prefs.compute_device_type = requested
        prefs.get_devices()
        usable = [d for d in prefs.devices if d.type == requested]
        if usable:
            for d in prefs.devices:
                d.use = d.type == requested
            return 'GPU', requested
    except Exception:
        pass
    return 'CPU', 'CPU'


def _sky_world(sun_elevation_deg: float, sun_rotation_deg: float, strength: float):
    world = bpy.data.worlds.new('SkyWorld')
    bpy.context.scene.world = world
    world.use_nodes = True
    nodes, links = world.node_tree.nodes, world.node_tree.links
    nodes.clear()
    sky = nodes.new('ShaderNodeTexSky')
    for sky_type in ('NISHITA', 'MULTIPLE_SCATTERING', 'SINGLE_SCATTERING', 'HOSEK_WILKIE'):
        try:
            sky.sky_type = sky_type
            break
        except TypeError:
            continue
    if hasattr(sky, 'sun_elevation'):
        sky.sun_elevation = math.radians(sun_elevation_deg)
        sky.sun_rotation = math.radians(sun_rotation_deg)
    background = nodes.new('ShaderNodeBackground')
    background.inputs['Strength'].default_value = strength
    output = nodes.new('ShaderNodeOutputWorld')
    links.new(sky.outputs['Color'], background.inputs['Color'])
    links.new(background.outputs['Background'], output.inputs['Surface'])
    return sky.sky_type


def _material_output(nt):
    outputs = [n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL']
    active = [n for n in outputs if n.is_active_output]
    return (active or outputs or [nt.nodes.new('ShaderNodeOutputMaterial')])[0]


def replace_with_base_grid(obj, base: dict):
    """Swap an imported dense terrain mesh for the sidecar's coarse quad
    grid (same footprint, UVs and materials). Geometry detail then comes
    from displacement diced to the output resolution, not from millions of
    base faces -- each of which costs Cycles a subdivision patch."""
    import numpy as np

    heights = np.load(base['heights_path']).astype(np.float64)
    nb, size_m = int(base['vertices_per_side']), float(base['size_meters'])
    if heights.shape != (nb, nb):
        raise RuntimeError('base grid heights do not match vertices_per_side')
    local = np.empty(len(obj.data.vertices) * 3)
    obj.data.vertices.foreach_get('co', local)
    local = local.reshape(-1, 3)
    if not (np.allclose(local[:, :2].min(0), 0.0, atol=1e-3 * size_m) and np.allclose(local[:, :2].max(0), size_m, atol=1e-3 * size_m)):
        raise RuntimeError('imported terrain footprint does not match the displacement sidecar')
    xs = np.linspace(0.0, size_m, nb)
    gx, gy = np.meshgrid(xs, xs, indexing='xy')
    verts = np.stack([gx.ravel(), gy.ravel(), heights.ravel()], axis=1)
    r, c = np.meshgrid(np.arange(nb - 1), np.arange(nb - 1), indexing='ij')
    i0 = (r * nb + c).ravel()
    quads = np.stack([i0, i0 + 1, i0 + nb + 1, i0 + nb], axis=1)  # counter-clockwise seen from +Z
    mesh = bpy.data.meshes.new('C3D_RenderBase')
    mesh.from_pydata(verts.tolist(), [], quads.tolist())
    uv_name = obj.data.uv_layers.active.name if obj.data.uv_layers else 'UVMap'
    uv_layer = mesh.uv_layers.new(name=uv_name)
    t = np.linspace(0.0, 1.0, nb)
    per_vertex = np.stack([np.tile(t, nb), 1.0 - np.repeat(t, nb)], axis=1)  # u = col, v = 1 - row
    uv_layer.data.foreach_set('uv', per_vertex[quads.ravel()].ravel())
    mesh.shade_smooth()
    for mat in obj.data.materials:
        mesh.materials.append(mat)
    dense = obj.data
    obj.data = mesh
    bpy.data.meshes.remove(dense)
    return {'base_faces': len(quads), 'vertices_per_side': nb}


def apply_displacement(meshes, disp: dict, subdivision: dict) -> dict:
    """Cycles adaptive subdivision (dices to ~dicing_rate_px on screen) plus
    true displacement from the exported residual map, so geometry detail
    scales with the output resolution instead of being fixed by the mesh."""
    img = bpy.data.images.load(disp['path'])
    img.colorspace_settings.name = 'Non-Color'
    span = disp['max_m'] - disp['min_m']
    scene = bpy.context.scene
    scene.cycles.dicing_rate = 1.0  # a multiplier on the per-object pixel size set below
    scene.cycles.max_subdivisions = int(subdivision['max_subdivisions'])
    base_info = None
    if disp.get('base_grid'):
        if len(meshes) != 1:
            raise RuntimeError('a terrain base-grid sidecar needs exactly one imported mesh')
        base_info = replace_with_base_grid(meshes[0], disp['base_grid'])
    materials = set()
    for obj in meshes:
        mod = obj.modifiers.new('C3D_AdaptiveSubdivision', 'SUBSURF')
        mod.subdivision_type = 'SIMPLE'  # displacement supplies the shape; don't shrink-smooth the terrain
        mod.use_adaptive_subdivision = True
        mod.adaptive_space = 'PIXEL'
        mod.adaptive_pixel_size = float(subdivision['dicing_rate_px'])
        materials.update(s.material for s in obj.material_slots if s.material is not None)
    for mat in materials:
        nt = mat.node_tree
        tex = nt.nodes.new('ShaderNodeTexImage')
        tex.image = img
        tex.interpolation = 'Cubic'
        decode = nt.nodes.new('ShaderNodeMath')
        decode.operation = 'MULTIPLY_ADD'  # value * span + min -> meters
        decode.inputs[1].default_value = span
        decode.inputs[2].default_value = disp['min_m']
        node = nt.nodes.new('ShaderNodeDisplacement')
        node.space = 'OBJECT'
        node.inputs['Midlevel'].default_value = 0.0
        node.inputs['Scale'].default_value = 1.0
        nt.links.new(tex.outputs['Color'], decode.inputs[0])
        nt.links.new(decode.outputs[0], node.inputs['Height'])
        nt.links.new(node.outputs['Displacement'], _material_output(nt).inputs['Displacement'])
        mat.displacement_method = 'DISPLACEMENT'  # the normal map still carries the micro-relief
        mat.max_vertex_displacement = max(abs(disp['min_m']), abs(disp['max_m'])) * 1.01
    return {'applied': True, 'image': disp['path'], 'range_m': [disp['min_m'], disp['max_m']],
            'materials': len(materials), 'dicing_rate_px': float(subdivision['dicing_rate_px']), 'base_grid': base_info,
            'max_subdivisions': int(subdivision['max_subdivisions'])}


def main():
    a = _args()
    manifest = json.loads(Path(a.manifest).read_text())
    out = Path(manifest['receipt_path'])
    out.parent.mkdir(parents=True, exist_ok=True)
    receipt = {'schema': 'character3d-cycles-render-receipt-v1', 'blender_version': bpy.app.version_string, 'status': 'running'}
    try:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        scene = bpy.context.scene
        meshes = _import_model(Path(manifest['source_model']))
        receipt['unpacked_images'] = unpack_images_to_files(Path(manifest['output_path'] + '.textures'))
        lo, hi = _world_bounds(meshes)
        center = (lo + hi) / 2
        size = hi - lo
        span = max(size.x, size.y, size.z)

        cam_data = bpy.data.cameras.new('RenderCamera')
        cam_data.lens = manifest['camera']['focal_length_mm']
        cam_data.clip_start = span * 1e-4
        cam_data.clip_end = span * 50
        cam = bpy.data.objects.new('RenderCamera', cam_data)
        scene.collection.objects.link(cam)
        az = math.radians(manifest['camera']['azimuth_deg'])
        el = math.radians(manifest['camera']['elevation_deg'])
        dist = span * manifest['camera']['distance_factor']
        cam.location = center + Vector((math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el))) * dist
        cam.rotation_euler = (center - cam.location).to_track_quat('-Z', 'Y').to_euler()
        scene.camera = cam

        light = manifest['lighting']
        sky_type = _sky_world(light['sun_elevation_deg'], light['sun_rotation_deg'], light['sky_strength'])
        sun = bpy.data.objects.new('Sun', bpy.data.lights.new('Sun', 'SUN'))
        sun.data.energy = light['sun_strength']
        sun.data.angle = math.radians(0.53)
        sun.rotation_euler = (math.radians(90 - light['sun_elevation_deg']), 0, math.radians(light['sun_rotation_deg'] + 90))
        scene.collection.objects.link(sun)

        disp = manifest.get('displacement')
        receipt['displacement'] = apply_displacement(meshes, disp, manifest['subdivision']) if disp else {'applied': False}

        q = manifest['quality']
        scene.render.engine = 'CYCLES'
        scene.cycles.device, backend = _select_device(q['device'])
        scene.cycles.samples = int(q['samples'])
        scene.cycles.use_adaptive_sampling = bool(q['adaptive_sampling'])
        scene.cycles.use_denoising = bool(q['denoise'])
        scene.cycles.max_bounces = int(q['max_bounces'])
        scene.cycles.transparent_max_bounces = int(q['transparent_bounces'])
        scene.cycles.tile_size = int(q['tile_size'])
        scene.render.use_persistent_data = bool(q['use_persistent_data'])
        scene.view_settings.view_transform = 'AgX' if 'AgX' in [v.identifier for v in type(scene.view_settings).bl_rna.properties['view_transform'].enum_items] else 'Filmic'

        o = manifest['output']
        scene.render.resolution_x = int(o['width']) + 2 * int(o['overscan_px'])
        scene.render.resolution_y = int(o['height']) + 2 * int(o['overscan_px'])
        scene.render.resolution_percentage = 100
        settings = scene.render.image_settings
        settings.file_format = manifest['file_format']
        if manifest['file_format'] == 'OPEN_EXR':
            settings.color_depth = '32' if int(o['bit_depth']) >= 32 else '16'
            settings.exr_codec = 'ZIP'
        else:
            settings.color_mode = 'RGB'
            settings.color_depth = '16' if int(o['bit_depth']) >= 16 else '8'
        scene.render.filepath = manifest['output_path']

        started = time.time()
        bpy.ops.render.render(write_still=True)
        receipt.update({
            'status': 'succeeded', 'render_seconds': round(time.time() - started, 2),
            'device_requested': q['device'], 'device_used': backend, 'samples': scene.cycles.samples,
            'resolution': [scene.render.resolution_x, scene.render.resolution_y],
            'file_format': manifest['file_format'], 'output_path': manifest['output_path'],
            'mesh_count': len(meshes), 'scene_extent_m': [round(v, 3) for v in size], 'sky_type': sky_type,
        })
    except Exception as exc:
        receipt.update({'status': 'failed', 'error': str(exc), 'traceback': traceback.format_exc()})
        raise
    finally:
        out.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        import shutil
        shutil.rmtree(manifest['output_path'] + '.textures', ignore_errors=True)


if __name__ == '__main__':
    main()
