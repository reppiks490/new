"""Character look-dev + portrait render worker (Cycles).

    blender --background --disable-autoexec --python character_lookdev.py -- --manifest job.json

Takes any character mesh (glb/gltf/fbx/obj/usd), assigns physically based
materials per role, lights it with a portrait rig and renders it:

- skin:  random-walk subsurface scattering with per-channel radii (red light
         travels furthest in tissue), a thin clear coat for the sebum film,
         pore-scale micro-bump, and base color from melanin + hemoglobin
         amounts (see skin_albedo) when the mesh has no color texture
- eyes:  refracting cornea shell (IOR 1.376) over a separate iris/sclera
         surface; roles come from material names or the manifest
- hair:  Principled Hair BSDF (Chiang) from melanin, for strand curves
- cloth: sheen layer for fibre fuzz
- rig:   key / fill / rim area lights sized from the head, rim behind so
         thin tissue (ears, nostrils) transmits red

Existing textures on the mesh are kept (color, normal, roughness); the
worker only adds what they lack. Role detection is by material-name
keywords unless manifest["roles"] maps material names explicitly.
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

ROLE_KEYWORDS = {
    'cornea': ('cornea', 'eyewet', 'eye_wet', 'tearline', 'eyeocclusion'),
    'eye': ('eye', 'iris', 'sclera', 'pupil'),
    'hair': ('hair', 'brow', 'lash', 'beard', 'groom', 'fur'),
    'cloth': ('cloth', 'shirt', 'jacket', 'pants', 'fabric', 'dress', 'coat', 'wool', 'denim', 'cotton'),
    'skin': ('skin', 'body', 'head', 'face', 'arm', 'leg', 'hand'),
}


def _args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument('--manifest', required=True)
    return p.parse_args(argv)


def skin_albedo(melanin: float, hemoglobin: float) -> tuple[float, float, float]:
    """Linear RGB diffuse albedo from chromophore amounts, a two-layer
    Beer-Lambert approximation of the epidermis (melanin) over the dermis
    (blood). melanin 0..1 (very fair .. very dark), hemoglobin 0..1
    (pale .. flushed). Absorption spectra sampled at ~610/550/465 nm."""
    melanin = min(max(melanin, 0.0), 1.0)
    hemoglobin = min(max(hemoglobin, 0.0), 1.0)
    mel_abs = (0.30, 0.55, 1.00)   # eumelanin absorbs blue strongest
    hb_abs = (0.05, 0.60, 0.45)    # oxy-hemoglobin: strong green, weak red
    base = (0.85, 0.72, 0.62)      # bloodless, melanin-free dermis
    out = []
    for b, m, h in zip(base, mel_abs, hb_abs):
        out.append(b * math.exp(-6.0 * melanin * m) * math.exp(-1.2 * hemoglobin * h))
    return tuple(out)


def _role(mat_name: str, overrides: dict) -> str | None:
    if mat_name in overrides:
        return overrides[mat_name]
    n = mat_name.lower()
    for role, words in ROLE_KEYWORDS.items():  # ordered: cornea before eye
        if any(w in n for w in words):
            return role
    return None


def _bsdf(mat):
    mat.use_nodes = True
    nt = mat.node_tree
    b = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if b is None:
        b = nt.nodes.new('ShaderNodeBsdfPrincipled')
        out = next((n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL'), None) or nt.nodes.new('ShaderNodeOutputMaterial')
        nt.links.new(b.outputs[0], out.inputs['Surface'])
    return nt, b


def _add_micro_bump(nt, bsdf, *, scale: float, strength: float, distance: float):
    coord = nt.nodes.new('ShaderNodeTexCoord')
    noise = nt.nodes.new('ShaderNodeTexVoronoi')  # cell-like pores
    noise.inputs['Scale'].default_value = scale
    bump = nt.nodes.new('ShaderNodeBump')
    bump.invert = True  # pores are pits
    bump.inputs['Strength'].default_value = strength
    bump.inputs['Distance'].default_value = distance
    nt.links.new(coord.outputs['Object'], noise.inputs['Vector'])
    nt.links.new(noise.outputs['Distance'], bump.inputs['Height'])
    if bsdf.inputs['Normal'].links:
        nt.links.new(bsdf.inputs['Normal'].links[0].from_socket, bump.inputs['Normal'])
    nt.links.new(bump.outputs['Normal'], bsdf.inputs['Normal'])


def apply_skin(mat, cfg: dict, unit_scale: float):
    nt, b = _bsdf(mat)
    if not b.inputs['Base Color'].links:
        b.inputs['Base Color'].default_value = (*skin_albedo(cfg.get('melanin', 0.25), cfg.get('hemoglobin', 0.5)), 1)
    b.subsurface_method = 'RANDOM_WALK_SKIN'
    b.inputs['Subsurface Weight'].default_value = 1.0
    # mean free path per channel in scene units: skin ~ (3.7, 1.4, 0.7) mm
    b.inputs['Subsurface Radius'].default_value = (1.0, 0.38, 0.19)
    b.inputs['Subsurface Scale'].default_value = 0.0037 / unit_scale
    b.inputs['Subsurface IOR'].default_value = 1.4
    if not b.inputs['Roughness'].links:
        b.inputs['Roughness'].default_value = 0.45
    b.inputs['Coat Weight'].default_value = 0.12       # sebum film
    b.inputs['Coat Roughness'].default_value = 0.35
    b.inputs['Coat IOR'].default_value = 1.45
    b.inputs['Specular IOR Level'].default_value = 0.5
    _add_micro_bump(nt, b, scale=1500.0 * unit_scale, strength=0.25, distance=0.0002 / unit_scale)


def apply_cornea(mat):
    nt, b = _bsdf(mat)
    b.inputs['Base Color'].default_value = (1, 1, 1, 1)
    b.inputs['Roughness'].default_value = 0.0
    b.inputs['IOR'].default_value = 1.376
    b.inputs['Transmission Weight'].default_value = 1.0
    b.inputs['Alpha'].default_value = 1.0


def apply_eye(mat):
    nt, b = _bsdf(mat)
    if not b.inputs['Base Color'].links:
        b.inputs['Base Color'].default_value = (0.8, 0.78, 0.75, 1)
    b.subsurface_method = 'RANDOM_WALK'
    b.inputs['Subsurface Weight'].default_value = 0.3  # sclera is translucent
    b.inputs['Subsurface Radius'].default_value = (1.0, 0.6, 0.5)
    b.inputs['Roughness'].default_value = 0.3


def apply_hair(mat, cfg: dict):
    nt = (mat.use_nodes or True) and mat.node_tree
    for n in list(nt.nodes):
        if n.type != 'OUTPUT_MATERIAL':
            nt.nodes.remove(n)
    out = next(n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL')
    h = nt.nodes.new('ShaderNodeBsdfHairPrincipled')
    h.parametrization = 'MELANIN'
    h.inputs['Melanin'].default_value = cfg.get('hair_melanin', 0.6)
    h.inputs['Melanin Redness'].default_value = cfg.get('hair_redness', 0.3)
    h.inputs['Roughness'].default_value = 0.25
    h.inputs['Radial Roughness'].default_value = 0.35
    h.inputs['Coat'].default_value = 0.05
    nt.links.new(h.outputs[0], out.inputs['Surface'])


def apply_cloth(mat):
    nt, b = _bsdf(mat)
    b.inputs['Sheen Weight'].default_value = 0.6
    b.inputs['Sheen Roughness'].default_value = 0.4
    if not b.inputs['Roughness'].links:
        b.inputs['Roughness'].default_value = 0.8


def _import(path: Path):
    ext = path.suffix.lower()
    if ext in ('.glb', '.gltf'):
        bpy.ops.import_scene.gltf(filepath=str(path))
    elif ext == '.fbx':
        bpy.ops.import_scene.fbx(filepath=str(path))
    elif ext == '.obj':
        bpy.ops.wm.obj_import(filepath=str(path))
    elif ext in ('.usd', '.usda', '.usdc', '.usdz'):
        bpy.ops.wm.usd_import(filepath=str(path))
    else:
        raise RuntimeError(f'unsupported character format {ext}')
    meshes = [o for o in bpy.context.scene.objects if o.type in ('MESH', 'CURVES')]
    if not meshes:
        raise RuntimeError('character file contains no meshes')
    return meshes


def _bounds(objs):
    pts = [o.matrix_world @ Vector(c) for o in objs if o.type == 'MESH' for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def portrait_rig(lo, hi, cfg: dict) -> dict:
    """Frames the head (top ~13% of a standing figure, or the whole mesh if
    it is only a head) and lights it: soft key 45 deg, dim fill, strong rim
    from behind. Returns what it did for the receipt."""
    height = hi.z - lo.z
    width = max(hi.x - lo.x, hi.y - lo.y)
    is_bust = height < 2.2 * width
    head_h = height if is_bust else height * 0.13
    target = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, hi.z - head_h * 0.5))
    scene = bpy.context.scene
    cam_data = bpy.data.cameras.new('C3D_PortraitCam')
    cam_data.lens = cfg.get('focal_length_mm', 85.0)
    cam_data.sensor_width = 36.0
    cam = bpy.data.objects.new('C3D_PortraitCam', cam_data)
    scene.collection.objects.link(cam)
    frame_h = head_h * cfg.get('framing', 1.6)
    dist = frame_h / 2 / math.tan(math.atan(24.0 / 2 / cam_data.lens))  # 24 mm vertical at 3:2
    az = math.radians(cfg.get('azimuth_deg', -20.0))
    cam.location = target + Vector((math.sin(az) * dist, -math.cos(az) * dist, head_h * 0.05))
    cam.rotation_euler = (target - cam.location).to_track_quat('-Z', 'Y').to_euler()
    scene.camera = cam
    if cfg.get('dof', True):
        cam_data.dof.use_dof = True
        cam_data.dof.focus_distance = dist
        cam_data.dof.aperture_fstop = cfg.get('fstop', 2.8)
    lights = []
    for name, (a_deg, elev_deg, energy_w, size_f, color) in {
        'key': (-45, 25, 60.0, 1.2, (1.0, 0.96, 0.9)),
        'fill': (50, 5, 12.0, 2.0, (0.9, 0.95, 1.0)),
        'rim': (160, 30, 90.0, 0.6, (1.0, 0.97, 0.94)),
    }.items():
        ld = bpy.data.lights.new(f'C3D_{name}', 'AREA')
        ld.shape = 'DISK'
        ld.size = head_h * size_f
        ld.color = color
        r = head_h * 3.0
        a, e = math.radians(a_deg), math.radians(elev_deg)
        # watts scale with distance^2 so exposure is independent of unit scale
        ld.energy = energy_w * (r / 0.6) ** 2
        lo_ = bpy.data.objects.new(f'C3D_{name}', ld)
        lo_.location = target + Vector((math.sin(a) * math.cos(e) * r, -math.cos(a) * math.cos(e) * r, math.sin(e) * r))
        lo_.rotation_euler = (target - lo_.location).to_track_quat('-Z', 'Y').to_euler()
        scene.collection.objects.link(lo_)
        lights.append(name)
    world = bpy.data.worlds.new('C3D_Studio')
    world.use_nodes = True
    bg = world.node_tree.nodes.get('Background')
    bg.inputs['Color'].default_value = (0.02, 0.022, 0.025, 1)
    bg.inputs['Strength'].default_value = 1.0
    scene.world = world
    return {'bust': is_bust, 'head_height': round(head_h, 4), 'camera_distance': round(dist, 4), 'lights': lights}


def main():
    a = _args()
    manifest = json.loads(Path(a.manifest).read_text())
    receipt_path = Path(manifest['receipt_path'])
    receipt = {'schema': 'character3d-lookdev-receipt-v1', 'blender_version': bpy.app.version_string, 'status': 'running'}
    try:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        scene = bpy.context.scene
        objs = _import(Path(manifest['source_model']))
        lo, hi = _bounds(objs)
        # meters per scene unit: glTF is meters; allow override for cm assets
        unit_scale = float(manifest.get('meters_per_unit', 1.0))
        cfg = manifest.get('lookdev', {})
        overrides = manifest.get('roles', {})
        roles = {}
        for mat in {s.material for o in objs for s in o.material_slots if s.material}:
            role = _role(mat.name, overrides)
            roles[mat.name] = role
            if role == 'skin':
                apply_skin(mat, cfg, unit_scale)
            elif role == 'cornea':
                apply_cornea(mat)
            elif role == 'eye':
                apply_eye(mat)
            elif role == 'hair':
                apply_hair(mat, cfg)
            elif role == 'cloth':
                apply_cloth(mat)
        if not any(r == 'skin' for r in roles.values()) and cfg.get('default_role_skin', True):
            for mat, r in list(roles.items()):
                if r is None:
                    apply_skin(bpy.data.materials[mat], cfg, unit_scale)
                    roles[mat] = 'skin (default)'
        for o in objs:
            if o.type == 'MESH' and not o.material_slots:
                m = bpy.data.materials.new('C3D_Skin')
                o.data.materials.append(m)
                apply_skin(m, cfg, unit_scale)
                roles[m.name] = 'skin (unassigned mesh)'
            if o.type == 'MESH':
                for p in o.data.polygons:
                    p.use_smooth = True
        receipt['roles'] = roles
        receipt['rig'] = portrait_rig(lo, hi, manifest.get('camera', {}))

        q = manifest.get('quality', {})
        scene.render.engine = 'CYCLES'
        scene.cycles.device = 'CPU'
        scene.cycles.samples = int(q.get('samples', 256))
        scene.cycles.use_adaptive_sampling = True
        scene.cycles.use_denoising = bool(q.get('denoise', True))
        scene.cycles.max_bounces = 16
        scene.cycles.transmission_bounces = 16
        scene.cycles.transparent_max_bounces = 32
        scene.view_settings.view_transform = 'AgX'
        try:
            scene.view_settings.look = 'AgX - Medium High Contrast'
        except TypeError:
            pass
        scene.render.resolution_x, scene.render.resolution_y = manifest.get('resolution', [1600, 2000])
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = 'PNG'
        scene.render.image_settings.color_mode = 'RGB'
        scene.render.image_settings.color_depth = '16'
        scene.render.filepath = manifest['output_path']
        t = time.time()
        bpy.ops.render.render(write_still=True)
        receipt.update(status='succeeded', render_seconds=round(time.time() - t, 2),
                       samples=scene.cycles.samples, resolution=[scene.render.resolution_x, scene.render.resolution_y],
                       output_path=manifest['output_path'])
    except Exception as exc:
        receipt.update(status='failed', error=str(exc), traceback=traceback.format_exc())
        raise
    finally:
        receipt_path.write_text(json.dumps(receipt, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
