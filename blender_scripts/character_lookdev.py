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


def _noise(nt, coord, scale, detail=6.0, rough=0.55):
    n = nt.nodes.new('ShaderNodeTexNoise')
    n.inputs['Scale'].default_value = scale
    n.inputs['Detail'].default_value = detail
    n.inputs['Roughness'].default_value = rough
    nt.links.new(coord.outputs['Object'], n.inputs['Vector'])
    return n.outputs['Fac']


def _remap(nt, sock, lo, hi):
    m = nt.nodes.new('ShaderNodeMapRange')
    m.inputs['To Min'].default_value, m.inputs['To Max'].default_value = lo, hi
    nt.links.new(sock, m.inputs['Value'])
    return m.outputs['Result']


def apply_skin(mat, cfg: dict, unit_scale: float):
    """Real skin is never one color or one gloss. On top of the chromophore
    albedo: blood-flush blotches (~4 cm), melanin mottling (~5 mm, freckle
    scale), roughness that varies 0.38-0.58 so highlights break up, a thin
    sebum coat, pores and fine wrinkles as bump. All in object space
    (meters, scaled by unit_scale) so it is seamless without UVs."""
    nt, b = _bsdf(mat)
    N, L = nt.nodes, nt.links
    coord = N.new('ShaderNodeTexCoord')
    u = 1.0 / unit_scale  # scene units per meter
    if not b.inputs['Base Color'].links:
        pale = skin_albedo(cfg.get('melanin', 0.25), cfg.get('hemoglobin', 0.5) * 0.6)
        flush = skin_albedo(cfg.get('melanin', 0.25), min(1.0, cfg.get('hemoglobin', 0.5) * 1.8))
        tan = skin_albedo(min(1.0, cfg.get('melanin', 0.25) + 0.12), cfg.get('hemoglobin', 0.5))
        blood = N.new('ShaderNodeMix'); blood.data_type = 'RGBA'
        L.new(_remap(nt, _noise(nt, coord, 25.0 / u, 4.0), 0.0, 1.0), blood.inputs['Factor'])
        blood.inputs[6].default_value = (*pale, 1); blood.inputs[7].default_value = (*flush, 1)
        mottle = N.new('ShaderNodeMix'); mottle.data_type = 'RGBA'
        mf = N.new('ShaderNodeMapRange'); mf.interpolation_type = 'SMOOTHSTEP'
        mf.inputs['From Min'].default_value, mf.inputs['From Max'].default_value = 0.55, 0.8
        mf.inputs['To Max'].default_value = cfg.get('freckles', 0.35)
        L.new(_noise(nt, coord, 200.0 / u, 3.0), mf.inputs['Value'])
        L.new(mf.outputs['Result'], mottle.inputs['Factor'])
        L.new(blood.outputs[2], mottle.inputs[6]); mottle.inputs[7].default_value = (*tan, 1)
        L.new(mottle.outputs[2], b.inputs['Base Color'])
    b.subsurface_method = 'RANDOM_WALK_SKIN'
    b.inputs['Subsurface Weight'].default_value = 1.0
    # mean free path per channel: skin ~ (3.7, 1.4, 0.7) mm
    b.inputs['Subsurface Radius'].default_value = (1.0, 0.38, 0.19)
    b.inputs['Subsurface Scale'].default_value = 0.0037 * u
    b.inputs['Subsurface IOR'].default_value = 1.4
    if not b.inputs['Roughness'].links:
        L.new(_remap(nt, _noise(nt, coord, 60.0 / u, 5.0), 0.38, 0.58), b.inputs['Roughness'])
    b.inputs['Coat Weight'].default_value = 0.04       # thin sebum film
    b.inputs['Coat Roughness'].default_value = 0.3
    b.inputs['Coat IOR'].default_value = 1.45
    b.inputs['Specular IOR Level'].default_value = 0.45
    # pores (~0.6 mm cells) + fine wrinkles (~3 mm) + large undulation
    prev = b.inputs['Normal'].links[0].from_socket if b.inputs['Normal'].links else None
    vor = N.new('ShaderNodeTexVoronoi'); vor.inputs['Scale'].default_value = 1600.0 / u
    L.new(coord.outputs['Object'], vor.inputs['Vector'])
    for height, strength, dist, invert in ((vor.outputs['Distance'], 0.5, 0.00012 * u, True),
                                           (_noise(nt, coord, 350.0 / u, 8.0, 0.65), 0.3, 0.0002 * u, False),
                                           (_noise(nt, coord, 40.0 / u, 3.0), 0.2, 0.0006 * u, False)):
        bump = N.new('ShaderNodeBump'); bump.invert = invert
        bump.inputs['Strength'].default_value = strength
        bump.inputs['Distance'].default_value = dist
        L.new(height, bump.inputs['Height'])
        if prev is not None:
            L.new(prev, bump.inputs['Normal'])
        prev = bump.outputs['Normal']
    L.new(prev, b.inputs['Normal'])


def apply_cornea(mat):
    nt, b = _bsdf(mat)
    b.inputs['Base Color'].default_value = (1, 1, 1, 1)
    b.inputs['Roughness'].default_value = 0.0
    b.inputs['IOR'].default_value = 1.376
    b.inputs['Transmission Weight'].default_value = 1.0
    b.inputs['Alpha'].default_value = 1.0


def apply_eye(mat, cfg: dict):
    """Sclera + procedural iris in object space (the eye object's origin
    must be the eyeball centre and it must look down -Y, as glTF/OBJ
    characters facing the viewer do): radial fibre noise, darker limbal
    ring, collarette, and a pupil sized by cfg['pupil']. Resolution-free,
    so it holds at 16K close-ups where an iris texture would blur."""
    nt, b = _bsdf(mat)
    N, L = nt.nodes, nt.links
    coord = N.new('ShaderNodeTexCoord')
    norm = N.new('ShaderNodeVectorMath'); norm.operation = 'NORMALIZE'
    sep = N.new('ShaderNodeSeparateXYZ')
    L.new(coord.outputs['Object'], norm.inputs[0]); L.new(norm.outputs[0], sep.inputs[0])
    fwd = N.new('ShaderNodeMath'); fwd.operation = 'MULTIPLY'; fwd.inputs[1].default_value = -1.0
    L.new(sep.outputs['Y'], fwd.inputs[0])  # d = cos(angle from gaze axis)

    def band(lo_, hi_):
        m = N.new('ShaderNodeMapRange'); m.interpolation_type = 'SMOOTHSTEP'
        m.inputs['From Min'].default_value, m.inputs['From Max'].default_value = lo_, hi_
        L.new(fwd.outputs[0], m.inputs['Value'])
        return m.outputs['Result']

    pupil_cos = 1.0 - 0.5 * cfg.get('pupil', 0.3) ** 2 * 0.35
    iris = band(0.842, 0.852)
    pupil = band(pupil_cos - 0.004, pupil_cos + 0.002)
    limbus = band(0.845, 0.875)
    ang = N.new('ShaderNodeMath'); ang.operation = 'ARCTAN2'
    L.new(sep.outputs['X'], ang.inputs[0]); L.new(sep.outputs['Z'], ang.inputs[1])
    polar = N.new('ShaderNodeCombineXYZ')
    a_s = N.new('ShaderNodeMath'); a_s.operation = 'MULTIPLY'; a_s.inputs[1].default_value = 6.0
    r_s = N.new('ShaderNodeMath'); r_s.operation = 'MULTIPLY'; r_s.inputs[1].default_value = 60.0
    L.new(ang.outputs[0], a_s.inputs[0]); L.new(fwd.outputs[0], r_s.inputs[0])
    L.new(a_s.outputs[0], polar.inputs['X']); L.new(r_s.outputs[0], polar.inputs['Y'])
    fib = N.new('ShaderNodeTexNoise'); fib.inputs['Scale'].default_value = 4.0
    fib.inputs['Detail'].default_value = 12.0; fib.inputs['Roughness'].default_value = 0.7
    L.new(polar.outputs[0], fib.inputs['Vector'])
    ramp = N.new('ShaderNodeValToRGB')
    dark, light = cfg.get('iris_dark', (0.03, 0.015, 0.006)), cfg.get('iris_light', (0.32, 0.17, 0.06))
    ramp.color_ramp.elements[0].color = (*dark, 1); ramp.color_ramp.elements[1].color = (*light, 1)
    L.new(fib.outputs['Fac'], ramp.inputs['Fac'])
    limb = N.new('ShaderNodeMix'); limb.data_type = 'RGBA'
    L.new(limbus, limb.inputs['Factor']); limb.inputs[6].default_value = (0.02, 0.012, 0.008, 1)
    L.new(ramp.outputs['Color'], limb.inputs[7])
    sclera = cfg.get('sclera', (0.78, 0.72, 0.68))
    mix_i = N.new('ShaderNodeMix'); mix_i.data_type = 'RGBA'
    L.new(iris, mix_i.inputs['Factor']); mix_i.inputs[6].default_value = (*sclera, 1)
    L.new(limb.outputs[2], mix_i.inputs[7])
    mix_p = N.new('ShaderNodeMix'); mix_p.data_type = 'RGBA'
    L.new(pupil, mix_p.inputs['Factor']); L.new(mix_i.outputs[2], mix_p.inputs[6])
    mix_p.inputs[7].default_value = (0.004, 0.004, 0.004, 1)
    L.new(mix_p.outputs[2], b.inputs['Base Color'])
    b.subsurface_method = 'RANDOM_WALK'
    b.inputs['Subsurface Weight'].default_value = 0.25  # sclera is translucent
    b.inputs['Subsurface Radius'].default_value = (1.0, 0.5, 0.4)
    b.inputs['Subsurface Scale'].default_value = 0.001
    b.inputs['Roughness'].default_value = 0.35


def apply_hair(mat, cfg: dict):
    nt = (mat.use_nodes or True) and mat.node_tree
    for n in list(nt.nodes):
        if n.type != 'OUTPUT_MATERIAL':
            nt.nodes.remove(n)
    out = next(n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL')
    h = nt.nodes.new('ShaderNodeBsdfHairPrincipled')
    h.parametrization = 'MELANIN'
    h.inputs['Melanin'].default_value = cfg.get('hair_melanin', 0.8)
    h.inputs['Melanin Redness'].default_value = cfg.get('hair_redness', 0.2)
    h.inputs['Roughness'].default_value = 0.25
    h.inputs['Radial Roughness'].default_value = 0.35
    h.inputs['Coat'].default_value = 0.05
    nt.links.new(h.outputs[0], out.inputs['Surface'])


def apply_cloth(mat, cfg: dict, unit_scale: float):
    """Woven fabric: base color with fibre-scale variation, sheen for the
    fuzz, and a weave bump (~1 mm threads) in object space."""
    nt, b = _bsdf(mat)
    N, L = nt.nodes, nt.links
    coord = N.new('ShaderNodeTexCoord')
    u = 1.0 / unit_scale
    if not b.inputs['Base Color'].links:
        c = cfg.get('cloth_color', (0.035, 0.045, 0.07))
        var = N.new('ShaderNodeMix'); var.data_type = 'RGBA'
        L.new(_noise(nt, coord, 300.0 / u, 4.0), var.inputs['Factor'])
        var.inputs[6].default_value = (*[x * 0.8 for x in c], 1); var.inputs[7].default_value = (*[x * 1.2 for x in c], 1)
        L.new(var.outputs[2], b.inputs['Base Color'])
    b.inputs['Sheen Weight'].default_value = 0.3
    b.inputs['Sheen Roughness'].default_value = 0.35
    b.inputs['Sheen Tint'].default_value = (0.6, 0.65, 0.8, 1)
    b.inputs['Roughness'].default_value = 0.85
    wave = N.new('ShaderNodeTexWave'); wave.inputs['Scale'].default_value = 900.0 / u
    wave.wave_type = 'BANDS'; wave.bands_direction = 'DIAGONAL'
    wave.inputs['Distortion'].default_value = 2.0
    L.new(coord.outputs['Object'], wave.inputs['Vector'])
    bump = N.new('ShaderNodeBump'); bump.inputs['Strength'].default_value = 0.35
    bump.inputs['Distance'].default_value = 0.0004 * u
    L.new(wave.outputs['Fac'], bump.inputs['Height'])
    L.new(bump.outputs['Normal'], b.inputs['Normal'])


def _surface_samples(obj, mask_fn, count, rng):
    """Area-weighted random points (+ normals) on the evaluated mesh's
    triangles whose centroid passes mask_fn(centroid) -> bool."""
    import numpy as np

    me = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
    me.calc_loop_triangles()
    co = np.empty(len(me.vertices) * 3, np.float32); me.vertices.foreach_get('co', co)
    co = (np.array(obj.matrix_world)[:3, :3] @ co.reshape(-1, 3).T).T + np.array(obj.matrix_world)[:3, 3]
    tri = np.empty(len(me.loop_triangles) * 3, np.int64); me.loop_triangles.foreach_get('vertices', tri)
    tri = tri.reshape(-1, 3)
    a, b_, c = co[tri[:, 0]], co[tri[:, 1]], co[tri[:, 2]]
    cen = (a + b_ + c) / 3
    keep = mask_fn(cen)
    a, b_, c = a[keep], b_[keep], c[keep]
    cross = np.cross(b_ - a, c - a)
    area = np.linalg.norm(cross, axis=1)
    if area.sum() == 0:
        return np.zeros((0, 3)), np.zeros((0, 3))
    pick = rng.choice(len(a), size=count, p=area / area.sum())
    r1, r2 = rng.random(count), rng.random(count)
    s1 = np.sqrt(r1)
    pts = (1 - s1)[:, None] * a[pick] + (s1 * (1 - r2))[:, None] * b_[pick] + (s1 * r2)[:, None] * c[pick]
    nrm = cross[pick] / area[pick][:, None]
    obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh_clear()
    return pts, nrm


def _hair_object(name, strands, radius_root, radius_tip, material):
    """strands: (N, K, 3) positions -> a Curves object with tapered radii."""
    import numpy as np

    n, k, _ = strands.shape
    hc = bpy.data.hair_curves.new(name)
    hc.add_curves([k] * n)
    hc.position_data.foreach_set('vector', strands.reshape(-1).astype(np.float32))
    taper = np.linspace(radius_root, radius_tip, k, dtype=np.float32)
    rad = hc.attributes.get('radius') or hc.attributes.new('radius', 'FLOAT', 'POINT')
    rad.data.foreach_set('value', np.tile(taper, n))
    hc.materials.append(material)
    ob = bpy.data.objects.new(name, hc)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def add_groom(skin_obj, eye_objs, cfg: dict, unit_scale: float) -> dict:
    """Strand hair, eyebrows and eyelashes grown from the skin surface.
    Scalp = above the hairline and behind the temples, located relative to
    the eyes (found from the eye objects), so it works for any head facing
    -Y. Strands leave along the normal and bend to gravity and away from a
    side part, with clump-coherent waviness; points are pushed out of the
    skull ellipsoid so hair lies on the head instead of through it."""
    import numpy as np

    rng = np.random.default_rng(cfg.get('seed', 3))
    u = 1.0 / unit_scale
    eyes = np.array([list(e.matrix_world.translation) for e in eye_objs])
    eye_c = eyes.mean(0)
    eye_sep = float(np.linalg.norm(eyes[0] - eyes[1])) if len(eyes) > 1 else 0.062 * u
    hs = eye_sep / 0.062  # head scale relative to an average adult
    crown_z = eye_c[2] + 0.125 * u * hs
    head_c = np.array([eye_c[0], eye_c[1] + 0.085 * u * hs, eye_c[2] + 0.03 * u * hs])
    made = {}
    mat = bpy.data.materials.new('C3D_Hair')
    apply_hair(mat, cfg)

    style = cfg.get('hair', {})
    if style.get('enabled', True):
        hairline_z = eye_c[2] + 0.062 * u * hs
        def scalp(p):
            behind_temple = p[:, 1] > eye_c[1] + 0.035 * u * hs
            above_ear = p[:, 2] > eye_c[2] - (0.02 if style.get('length_m', 0.14) > 0.08 else -0.01) * u * hs
            return ((p[:, 2] > hairline_z) & (p[:, 1] > eye_c[1] - 0.02 * u * hs)) | (behind_temple & above_ear)
        n = int(style.get('strands', 60000))
        roots, nrm = _surface_samples(skin_obj, scalp, n, rng)
        k = 14
        length = style.get('length_m', 0.14) * u * hs * rng.uniform(0.75, 1.15, n)
        part_x = eye_c[0] + style.get('part_offset_m', 0.025) * u * hs
        side = np.sign(roots[:, 0] - part_x)[:, None] * np.array([1.0, 0.0, 0.0])
        # 0 at the hairline front .. 1 behind the ears
        front = np.clip((roots[:, 1] - (eye_c[1] + 0.01 * u * hs)) / (0.09 * u * hs), 0.0, 1.0)[:, None]
        back = np.array([0.0, 1.0, 0.0]) * (1.6 - 1.25 * front)
        down = np.array([0.0, 0.0, -1.0]) * (0.25 + 0.75 * front)
        # clump-coherent wave: low-frequency function of root position
        f = 60.0 / u
        wave_phase = np.sin(roots[:, 0] * f * 1.7) + np.cos(roots[:, 1] * f * 1.3) + np.sin(roots[:, 2] * f)
        radius0 = np.linalg.norm((roots - head_c) / np.array([1.0, 1.1, 1.15]), axis=1)
        strands = np.empty((n, k, 3))
        p = roots + nrm * 0.0005 * u
        strands[:, 0] = p
        for i in range(1, k):
            t = i / (k - 1)
            d = nrm * (1 - t) ** 2 * 1.2 + (side * 0.9 + back) * (1 - t) + down * (0.3 + 1.4 * t)
            d += np.stack([np.sin(wave_phase + t * 7.0), np.cos(wave_phase * 1.3 + t * 6.0), np.zeros(n)], 1) * style.get('wave', 0.25)
            d /= np.linalg.norm(d, axis=1, keepdims=True)
            p = p + d * (length / (k - 1))[:, None]
            rel = (p - head_c) / np.array([1.0, 1.1, 1.15])
            r = np.linalg.norm(rel, axis=1)
            min_r = radius0 + 0.004 * u * hs * t + 0.0015 * u * hs
            push = np.where(r < min_r, min_r / np.maximum(r, 1e-9), 1.0)
            p = head_c + rel * push[:, None] * np.array([1.0, 1.1, 1.15])
            strands[:, i] = p
        # locks: every strand is pulled toward its nearest guide strand's shape,
        # increasingly toward the tip, so hair reads as clumps, not a sheet
        g = max(1, int(style.get('clumps', 1800)))
        gi = rng.choice(n, size=min(g, n), replace=False)
        nearest = np.empty(n, np.int64)
        for c0 in range(0, n, 4096):
            d2 = ((roots[c0:c0 + 4096, None, :] - roots[None, gi, :]) ** 2).sum(-1)
            nearest[c0:c0 + 4096] = gi[d2.argmin(1)]
        t = np.linspace(0.0, 1.0, k)[None, :, None]
        clump = style.get('clump', 0.75)
        target = strands[nearest] + (roots - roots[nearest])[:, None, :] * (1 - 0.85 * t)
        strands = strands + (target - strands) * (clump * t ** 0.8)
        _hair_object('C3D_Hair', strands, 0.00004 * u, 0.00001 * u, mat)
        made['hair_strands'] = n
        made['hair_clumps'] = len(gi)

    for side_sign, eye in zip(np.sign(eyes[:, 0] - eye_c[0]), eyes):
        def brow(p, eye=eye, s=side_sign):
            dx = (p[:, 0] - eye[0]) * s
            dz = p[:, 2] - (eye[2] + 0.017 * u * hs + 0.006 * u * hs * np.clip(dx / (0.02 * u * hs), -1, 1) - 0.004 * u * hs * np.clip(dx / (0.02 * u * hs), 0, 1) ** 2)
            return (np.abs(dz) < 0.0045 * u * hs) & (dx > -0.022 * u * hs) & (dx < 0.028 * u * hs) & (p[:, 1] < eye[1] + 0.012 * u * hs)
        n = int(cfg.get('brow_strands', 1200))
        roots, nrm = _surface_samples(skin_obj, brow, n, rng)
        if len(roots):
            k = 5
            lateral = np.array([side_sign, 0.0, 0.35])
            strands = np.empty((n, k, 3))
            for i in range(k):
                t = i / (k - 1)
                d = lateral / np.linalg.norm(lateral) * (0.009 * u * hs * t) * rng.uniform(0.7, 1.2, n)[:, None]
                strands[:, i] = roots + nrm * (0.0012 * u * hs * np.sin(t * np.pi / 2)) + d
            _hair_object('C3D_Brow', strands, 0.000025 * u, 0.000008 * u, mat)
            made['brow_strands'] = made.get('brow_strands', 0) + n

        # eyelashes along the upper lid arc, curling up and out
        m, k = int(cfg.get('lashes', 90)), 6
        er = 0.0125 * u * hs
        ang = np.linspace(np.radians(25), np.radians(155), m) + rng.normal(0, 0.02, m)
        base = eye + np.stack([np.cos(ang) * er * 1.05 * side_sign * -1, -np.full(m, er * 0.55), np.sin(ang) * er * 0.45 + er * 0.25], 1)
        out = np.stack([np.cos(ang) * 0.3 * -side_sign, -np.ones(m), np.full(m, 0.35)], 1)
        out /= np.linalg.norm(out, axis=1, keepdims=True)
        strands = np.empty((m, k, 3))
        ln = 0.009 * u * hs * rng.uniform(0.7, 1.1, m)
        for i in range(k):
            t = i / (k - 1)
            strands[:, i] = base + out * (ln * t)[:, None] + np.array([0, 0, 1.0]) * (ln * 0.6 * t ** 2)[:, None]
        _hair_object('C3D_Lashes', strands, 0.00006 * u, 0.00001 * u, mat)
        made['lashes'] = made.get('lashes', 0) + m
    return made


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
    subject = cfg.get('subject', 'auto')
    is_bust = subject == 'bust' or (subject == 'auto' and height < 1.0 * cfg.get('units_per_meter', 1.0))
    head_h = height if is_bust else height * 0.13
    frame_h = head_h * cfg.get('framing', 1.75)  # head + neck + collar
    # aim below the eye line by 1/6 frame so the eyes sit on the upper third
    target = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, hi.z - head_h * 0.55 - frame_h / 6))
    scene = bpy.context.scene
    cam_data = bpy.data.cameras.new('C3D_PortraitCam')
    cam_data.lens = cfg.get('focal_length_mm', 85.0)
    cam_data.sensor_width = 36.0
    cam = bpy.data.objects.new('C3D_PortraitCam', cam_data)
    scene.collection.objects.link(cam)
    dist = frame_h / 2 / math.tan(math.atan(24.0 / 2 / cam_data.lens))  # 24 mm vertical at 3:2
    az = math.radians(cfg.get('azimuth_deg', -20.0))
    cam.location = target + Vector((math.sin(az) * dist, -math.cos(az) * dist, head_h * 0.05))
    cam.rotation_euler = (target - cam.location).to_track_quat('-Z', 'Y').to_euler()
    scene.camera = cam
    if cfg.get('dof', True):
        cam_data.dof.use_dof = True
        focus = Vector(cfg['focus_point']) if cfg.get('focus_point') else target
        cam_data.dof.focus_distance = (focus - cam.location).length  # eyes sharp
        cam_data.dof.aperture_fstop = cfg.get('fstop', 8.0)
    lights = []
    for name, (a_deg, elev_deg, energy_w, size_f, color) in {
        'key': (-45, 25, 28.0, 1.4, (1.0, 0.96, 0.9)),
        'fill': (50, 5, 5.0, 2.5, (0.9, 0.95, 1.0)),
        'rim': (160, 30, 55.0, 0.6, (1.0, 0.97, 0.94)),
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
                apply_eye(mat, cfg)
            elif role == 'hair':
                apply_hair(mat, cfg)
            elif role == 'cloth':
                apply_cloth(mat, cfg, unit_scale)
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
                slot_roles = {roles.get(s.material.name) for s in o.material_slots if s.material}
                if slot_roles & {'skin', 'skin (default)', 'cloth'} and len(o.data.polygons) < 200_000:
                    sub = o.modifiers.new('C3D_Subdiv', 'SUBSURF')
                    sub.levels, sub.render_levels = 0, int(manifest.get('subdivision_levels', 2))
        receipt['roles'] = roles
        groom = manifest.get('groom', {})
        if groom.get('enabled', True):
            skin_objs = [o for o in objs if o.type == 'MESH' and any(
                s.material and roles.get(s.material.name, '').startswith('skin') for s in o.material_slots)]
            eye_objs = [o for o in objs if o.type == 'MESH' and any(
                s.material and roles.get(s.material.name) == 'eye' for s in o.material_slots)]
            if skin_objs and eye_objs:
                skin = max(skin_objs, key=lambda o: len(o.data.polygons))
                receipt['groom'] = add_groom(skin, eye_objs, {**cfg, **groom}, unit_scale)
        cam_cfg = dict(manifest.get('camera', {}))
        eye_centres = [o.matrix_world.translation for o in objs if o.type == 'MESH' and any(
            s.material and roles.get(s.material.name) == 'eye' for s in o.material_slots)]
        if eye_centres and 'focus_point' not in cam_cfg:
            cam_cfg['focus_point'] = list(sum(eye_centres, Vector()) / len(eye_centres))
        receipt['rig'] = portrait_rig(lo, hi, cam_cfg)

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
