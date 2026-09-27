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


if __name__ == '__main__':
    main()
