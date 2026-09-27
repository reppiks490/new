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
        # REMOVE drops the packed copy and keeps filepath; USE_ORIGINAL
        # re-writes the image under its name relative to the CWD
        img.unpack(method='REMOVE')
        img.filepath = str(target)
        img.reload()
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
    scene.cycles.offscreen_dicing_scale = float(subdivision.get('offscreen_dicing_scale', 4.0))
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


def add_surface_detail(terrain) -> dict:
    """Breaks the 'painted' look: textures stop at their texel size (12 cm
    at 16K over 2 km), so up close the ground reads as smooth paint. Adds
    render-time detail below that scale -- multiplicative color variation
    (+/-12 %) and bump from noise at ~2 m, 25 cm and 3 cm -- on top of
    the baked maps, in object space, so it's seamless and costs no memory."""
    done = 0
    for slot in terrain.material_slots:
        mat = slot.material
        if mat is None or not mat.node_tree:
            continue
        nt = mat.node_tree
        bsdf = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if bsdf is None:
            continue
        coord = nt.nodes.new('ShaderNodeTexCoord')
        base_link = bsdf.inputs['Base Color'].links[0] if bsdf.inputs['Base Color'].links else None
        if base_link is not None:
            var = nt.nodes.new('ShaderNodeTexNoise')
            var.inputs['Scale'].default_value = 0.45
            var.inputs['Detail'].default_value = 8.0
            ramp = nt.nodes.new('ShaderNodeMapRange')
            ramp.inputs['To Min'].default_value = 0.88
            ramp.inputs['To Max'].default_value = 1.12
            mul = nt.nodes.new('ShaderNodeMix')
            mul.data_type = 'RGBA'
            mul.blend_type = 'MULTIPLY'
            mul.inputs['Factor'].default_value = 1.0
            nt.links.new(coord.outputs['Object'], var.inputs['Vector'])
            nt.links.new(var.outputs['Fac'], ramp.inputs['Value'])
            nt.links.new(base_link.from_socket, mul.inputs[6])
            nt.links.new(ramp.outputs['Result'], mul.inputs[7])
            nt.links.new(mul.outputs[2], bsdf.inputs['Base Color'])
        normal_in = bsdf.inputs['Normal'].links[0].from_socket if bsdf.inputs['Normal'].links else None
        prev = normal_in
        for scale, strength, dist in ((0.5, 0.25, 0.3), (4.0, 0.35, 0.05), (33.0, 0.3, 0.01)):
            noise = nt.nodes.new('ShaderNodeTexNoise')
            noise.inputs['Scale'].default_value = scale
            noise.inputs['Detail'].default_value = 6.0
            noise.inputs['Roughness'].default_value = 0.6
            bump = nt.nodes.new('ShaderNodeBump')
            bump.inputs['Strength'].default_value = strength
            bump.inputs['Distance'].default_value = dist
            nt.links.new(coord.outputs['Object'], noise.inputs['Vector'])
            nt.links.new(noise.outputs['Fac'], bump.inputs['Height'])
            if prev is not None:
                nt.links.new(prev, bump.inputs['Normal'])
            prev = bump.outputs['Normal']
        nt.links.new(prev, bsdf.inputs['Normal'])
        done += 1
    return {'materials': done}


def add_atmosphere(terrain, disp: dict, density: float) -> dict:
    """Aerial perspective: a thin scattering + absorbing volume over the
    terrain (mean free path 1/density m), so distance hazes and blues the
    way real air does instead of staying painted-crisp to the horizon."""
    size_m = float(disp['base_grid']['size_meters'])
    top = float(disp.get('max_height_m', 0.0)) + size_m * 0.5
    pad = size_m * 1.0  # the sky beyond stays clear: Nishita already carries the far atmosphere
    mesh = bpy.data.meshes.new('C3D_Atmosphere')
    lo, hi = (-pad, -pad, -50.0), (size_m + pad, size_m + pad, top)
    v = [(x, y, z) for z in (lo[2], hi[2]) for y in (lo[1], hi[1]) for x in (lo[0], hi[0])]
    f = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    mesh.from_pydata(v, [], f)
    obj = bpy.data.objects.new('C3D_Atmosphere', mesh)
    obj.matrix_world = terrain.matrix_world
    bpy.context.scene.collection.objects.link(obj)
    mat = bpy.data.materials.new('C3D_Atmosphere')
    nt = mat.node_tree
    for n in list(nt.nodes):
        if n.type != 'OUTPUT_MATERIAL':
            nt.nodes.remove(n)
    vol = nt.nodes.new('ShaderNodeVolumePrincipled')
    vol.inputs['Color'].default_value = (0.62, 0.74, 0.95, 1)  # Rayleigh-ish: scatters blue
    vol.inputs['Density'].default_value = density
    vol.inputs['Anisotropy'].default_value = 0.6  # forward-scattering haze glows toward the sun
    vol.inputs['Absorption Color'].default_value = (0.85, 0.9, 1.0, 1)
    nt.links.new(vol.outputs['Volume'], _material_output(nt).inputs['Volume'])
    mesh.materials.append(mat)
    bpy.context.scene.cycles.volume_max_steps = 256
    return {'applied': True, 'density_per_m': density, 'mean_free_path_m': round(1.0 / density)}


def add_water(terrain, disp: dict) -> dict:
    """A real water surface over the flattened (painted) sea: clear,
    refractive (IOR 1.333) and reflective, with a two-octave wave normal, so
    the painted depth colors read through it as the bed and the sky and
    shore reflect. Sits 5 cm above the flattened level to avoid z-fighting."""
    import numpy as np

    level = disp.get('water_level_m')
    if level is None:  # older sidecars: the flattened sea is the base grid minimum
        level = float(np.load(disp['base_grid']['heights_path']).min())
    size_m = float(disp['base_grid']['size_meters'])
    mesh = bpy.data.meshes.new('C3D_Water')
    z = level + 0.05
    mesh.from_pydata([(0, 0, z), (size_m, 0, z), (size_m, size_m, z), (0, size_m, z)], [], [(0, 1, 2, 3)])
    obj = bpy.data.objects.new('C3D_Water', mesh)
    obj.matrix_world = terrain.matrix_world
    bpy.context.scene.collection.objects.link(obj)
    mat = bpy.data.materials.new('C3D_Water')
    nt = mat.node_tree
    bsdf = nt.nodes.get('Principled BSDF') or nt.nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.inputs['Base Color'].default_value = (0.75, 0.9, 0.92, 1)
    bsdf.inputs['Roughness'].default_value = 0.02
    bsdf.inputs['IOR'].default_value = 1.333
    bsdf.inputs['Transmission Weight'].default_value = 1.0
    coord = nt.nodes.new('ShaderNodeTexCoord')
    bumps, prev = [], None
    for scale, strength in ((0.08, 0.35), (0.9, 0.12)):  # swell (~12 m) + chop (~1 m)
        noise = nt.nodes.new('ShaderNodeTexNoise')
        noise.inputs['Scale'].default_value = scale
        noise.inputs['Detail'].default_value = 6.0
        bump = nt.nodes.new('ShaderNodeBump')
        bump.inputs['Strength'].default_value = strength
        bump.inputs['Distance'].default_value = 0.2
        nt.links.new(coord.outputs['Object'], noise.inputs['Vector'])
        nt.links.new(noise.outputs['Fac'], bump.inputs['Height'])
        if prev is not None:
            nt.links.new(prev.outputs['Normal'], bump.inputs['Normal'])
        prev = bump
    nt.links.new(prev.outputs['Normal'], bsdf.inputs['Normal'])
    mesh.materials.append(mat)
    return {'applied': True, 'level_m': round(z, 3)}


def _strip_to_raw(png: Path, strip: dict) -> dict:
    """Re-read this strip's PNG (encoded values, no color transform) and
    save top-down uint16 RGB rows for the stitcher -- which then needs no
    16-bit PNG decoder of its own."""
    import numpy as np

    img = bpy.data.images.load(str(png))
    img.colorspace_settings.name = 'Non-Color'
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    rows = px.reshape(h, w, 4)[::-1, :, :3]
    raw = Path(strip['raw_path'])
    np.save(raw, np.round(np.clip(rows, 0.0, 1.0) * 65535.0).astype(np.uint16))
    bpy.data.images.remove(img)
    return {'rows': h, 'width': w, 'raw_path': str(raw), 'y0': strip['y0'], 'y1': strip['y1']}


def main():
    a = _args()
    manifest = json.loads(Path(a.manifest).read_text())
    out = Path(manifest['receipt_path'])
    out.parent.mkdir(parents=True, exist_ok=True)
    receipt = {'schema': 'character3d-cycles-render-receipt-v1', 'blender_version': bpy.app.version_string, 'status': 'running'}
    try:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        scene = bpy.context.scene
        source = Path(manifest['source_model'])
        disp = manifest.get('displacement')
        if disp and disp.get('base_grid') and source.suffix.lower() == '.glb':
            # the dense mesh would be replaced by the base grid anyway: import
            # a quad-geometry proxy with the same materials and image bytes
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from glb_proxy import write_terrain_proxy
            proxy = Path(manifest['output_path'] + '.textures') / 'terrain_proxy.glb'
            receipt['proxy_import'] = write_terrain_proxy(source, proxy)
            if receipt['proxy_import']:
                source = proxy
        meshes = _import_model(source)
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

        receipt['displacement'] = apply_displacement(meshes, disp, manifest['subdivision']) if disp else {'applied': False}
        veg = manifest.get('vegetation')
        if veg and disp:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from vegetation import scatter_vegetation
            terrain = next(o for o in bpy.context.scene.objects if o.type == 'MESH' and 'C3D_AdaptiveSubdivision' in o.modifiers)
            receipt['vegetation'] = scatter_vegetation(terrain, disp, veg, seed=int(veg.get('seed', 7)))
        else:
            receipt['vegetation'] = {'applied': False}
        if disp and disp.get('base_grid') and manifest.get('water', True):
            terrain = next(o for o in bpy.context.scene.objects if o.type == 'MESH' and 'C3D_AdaptiveSubdivision' in o.modifiers)
            receipt['water'] = add_water(terrain, disp)
            receipt['surface_detail'] = add_surface_detail(terrain)
            if manifest.get('atmosphere_density_per_m'):
                receipt['atmosphere'] = add_atmosphere(terrain, disp, float(manifest['atmosphere_density_per_m']))

        q = manifest['quality']
        scene.render.engine = 'CYCLES'
        scene.cycles.device, backend = _select_device(q['device'])
        scene.cycles.samples = int(q['samples'])
        scene.cycles.use_adaptive_sampling = bool(q['adaptive_sampling'])
        scene.cycles.use_denoising = bool(q['denoise'])
        scene.cycles.max_bounces = int(q['max_bounces'])
        scene.cycles.transparent_max_bounces = int(q['transparent_bounces'])
        scene.cycles.tile_size = int(q['tile_size'])
        # one still per process: persistent data would only keep a second
        # synced copy of the scene alive (measured +1.6 GB on 16K terrain)
        scene.render.use_persistent_data = False
        receipt['persistent_data_requested'] = bool(q['use_persistent_data'])
        scene.view_settings.view_transform = 'AgX' if 'AgX' in [v.identifier for v in type(scene.view_settings).bl_rna.properties['view_transform'].enum_items] else 'Filmic'
        # the look enum is filled dynamically (lists only NONE when read), so assign
        for look in ('AgX - Medium High Contrast', 'Medium High Contrast'):
            try:
                scene.view_settings.look = look
                break
            except TypeError:
                continue
        receipt['look'] = scene.view_settings.look

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
        strip = manifest.get('strip')
        if strip:
            # rows [y0, y1) counted from the top; Blender's border is
            # fractional and counted from the bottom
            H = scene.render.resolution_y
            scene.render.use_border = True
            scene.render.use_crop_to_border = True
            scene.render.border_min_x, scene.render.border_max_x = 0.0, 1.0
            scene.render.border_min_y = 1.0 - strip['y1'] / H
            scene.render.border_max_y = 1.0 - strip['y0'] / H

        started = time.time()
        bpy.ops.render.render(write_still=True)
        if strip:
            receipt['strip'] = _strip_to_raw(Path(manifest['output_path']), strip)
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
