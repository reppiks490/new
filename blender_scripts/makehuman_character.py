"""Builds a realistic base character from the CC0 MakeHuman base mesh.

    blender --background --python makehuman_character.py -- BASE_OBJ OUT_GLB [TARGET:WEIGHT ...]

TARGETs are MakeHuman .target files (CC0; "index dx dy dz" per line, in the
base mesh's decimeter Y-up frame) blended onto the base before import --
e.g. caucasian-male-young.target:0.34 african-male-young.target:0.33
asian-male-young.target:0.33 is MakeHuman's default young adult male.

MakeHuman's base.obj and high-poly eyes (released CC0, Sept 2020; see the
header of each file) give production human topology -- 13K-quad body with
real eye sockets, lids, lips and ears -- that primitives cannot. This
script applies shape targets, keeps only the body group (drops helper/joint
proxies), converts decimeters to meters, fits eyeballs (origin at the
centre; the look-dev iris shader works in object space) and refracting
cornea shells to the base mesh's eye helpers, and cuts a crew-neck shirt
from the torso with clean planes so portraits are clothed. Material names carry the
roles the look-dev stage keys on.
"""
from __future__ import annotations

import math
import sys

import bmesh
import bpy
from mathutils import Vector


def _only(obj):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _import_obj(path: str, split_groups: bool):
    before = set(bpy.data.objects)
    bpy.ops.wm.obj_import(filepath=path, use_split_groups=split_groups, use_split_objects=False)
    return [o for o in bpy.data.objects if o not in before]


def _material(name: str):
    return bpy.data.materials.get(name) or bpy.data.materials.new(name)


def apply_targets(base_obj: str, targets: list[tuple[str, float]], out_obj: str) -> int:
    """Blend MakeHuman targets onto the base mesh's vertex lines (vertex
    order in the OBJ is the target index space)."""
    lines = open(base_obj).read().splitlines()
    v_idx = [i for i, ln in enumerate(lines) if ln.startswith('v ')]
    offs = {}
    for path, w in targets:
        for ln in open(path):
            if ln.startswith('#') or not ln.strip():
                continue
            i, dx, dy, dz = ln.split()
            o = offs.setdefault(int(i), [0.0, 0.0, 0.0])
            o[0] += w * float(dx); o[1] += w * float(dy); o[2] += w * float(dz)
    for i, (dx, dy, dz) in offs.items():
        ln = lines[v_idx[i]].split()
        lines[v_idx[i]] = f'v {float(ln[1]) + dx:.6f} {float(ln[2]) + dy:.6f} {float(ln[3]) + dz:.6f}'
    open(out_obj, 'w').write('\n'.join(lines) + '\n')
    return len(offs)


def main():
    argv = sys.argv[sys.argv.index('--') + 1:]
    base_obj, out_glb = argv[:2]
    targets = [(a.rsplit(':', 1)[0], float(a.rsplit(':', 1)[1])) for a in argv[2:]]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if targets:
        import tempfile
        shaped = tempfile.NamedTemporaryFile(suffix='.obj', delete=False).name
        apply_targets(base_obj, targets, shaped)
        base_obj = shaped

    parts = _import_obj(base_obj, split_groups=True)
    body = next(o for o in parts if o.name.split('.')[0] == 'body')
    # the base mesh's own eye helpers mark the exact sockets; the separate
    # eyes proxy file uses another frame (measured ~0.85 m off), so eyeballs
    # are fitted to the helpers instead
    sockets = {}
    for side in ('l', 'r'):
        helper = next(o for o in parts if o.name.split('.')[0] == f'helper-{side}-eye')
        pts = [helper.matrix_world @ v.co * 0.1 for v in helper.data.vertices]
        c = sum(pts, Vector()) / len(pts)
        sockets[side] = (c, sum((p - c).length for p in pts) / len(pts))
    for o in parts:
        if o is not body:
            bpy.data.objects.remove(o)
    body.name = 'Body'
    body.data.materials.clear()
    body.data.materials.append(_material('Skin_Body'))
    body.scale = (0.1, 0.1, 0.1)  # MakeHuman units are decimeters
    _only(body)
    bpy.ops.object.transform_apply(scale=True)
    bm = bmesh.new()
    bm.from_mesh(body.data)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
    bm.to_mesh(body.data)
    bm.free()
    ground = min(v.co.z for v in body.data.vertices)
    body.location.z -= ground  # feet on the ground
    _only(body)
    bpy.ops.object.transform_apply(location=True)

    for side, (c, r) in sockets.items():
        name = 'R' if side == 'r' else 'L'
        center = c + Vector((0, 0, -ground))
        bpy.ops.mesh.primitive_uv_sphere_add(segments=96, ring_count=64, radius=r, location=center)
        eye = bpy.context.object
        eye.name = f'Eye_{name}'
        eye.data.materials.append(_material('Eye_Sclera'))
        bpy.ops.object.shade_smooth()
        bpy.ops.mesh.primitive_uv_sphere_add(segments=96, ring_count=64, radius=r * 1.02, location=center)
        cornea = bpy.context.object
        cornea.name = f'Cornea_{name}'
        cornea.data.materials.append(_material('Cornea_Wet'))
        bpy.ops.object.shade_smooth()

    # crew-neck shirt: the body cut by clean planes (neckline dipping at the
    # front, hem, short sleeves), then thickened and eased 4 mm off the skin
    lo = min(v.co.z for v in body.data.vertices)
    hi = max(v.co.z for v in body.data.vertices)
    h = hi - lo
    shirt = body.copy()
    shirt.data = body.data.copy()
    shirt.name = 'Shirt'
    bpy.context.scene.collection.objects.link(shirt)
    bm = bmesh.new()
    bm.from_mesh(shirt.data)
    cuts = [((0, 0, lo + h * 0.86), Vector((0, 0, 1))),                   # above the shoulders
            ((0, 0, lo + h * 0.52), Vector((0, 0, -1))),                   # hem
            ((h * 0.17, 0, 0), Vector((1, 0, 0))), ((-h * 0.17, 0, 0), Vector((-1, 0, 0)))]  # sleeves
    for co, no in cuts:
        geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
        bmesh.ops.bisect_plane(bm, geom=geom, plane_co=co, plane_no=no, clear_outer=True)
    # keep only the torso piece (drops stray islands such as fingertips)
    islands, seen = [], set()
    for f in bm.faces:
        if f in seen:
            continue
        stack, isl = [f], []
        seen.add(f)
        while stack:
            g = stack.pop(); isl.append(g)
            for e in g.edges:
                for n in e.link_faces:
                    if n not in seen:
                        seen.add(n); stack.append(n)
        islands.append(isl)
    keep = max(islands, key=len)
    bmesh.ops.delete(bm, geom=[f for isl in islands if isl is not keep for f in isl], context='FACES')
    bm.to_mesh(shirt.data)
    bm.free()
    # crew neck: an elliptic cylinder around the neck, tilted so the front
    # dips, boolean-cut out -- a clean round collar that hugs the neck base
    neck = [v.co for v in body.data.vertices if lo + h * 0.855 < v.co.z < lo + h * 0.875 and abs(v.co.x) < h * 0.05]
    nc = sum(neck, Vector()) / max(len(neck), 1)
    # short cylinder whose bottom cap is the collar line: at the neck base
    # behind, dipping ~2.5 cm in front (tilt +20 deg about X lowers the front)
    depth = h * 0.1
    bpy.ops.mesh.primitive_cylinder_add(vertices=96, radius=1.0, depth=depth, location=(nc.x, nc.y, lo + h * 0.848 + depth / 2))
    cutter = bpy.context.object
    cutter.scale = (h * 0.045, h * 0.043, 1.0)
    cutter.rotation_euler = (math.radians(20), 0, 0)
    boolean = shirt.modifiers.new('neck', 'BOOLEAN')
    boolean.operation = 'DIFFERENCE'
    boolean.object = cutter
    _only(shirt)
    bpy.ops.object.modifier_apply(modifier='neck')
    bpy.data.objects.remove(cutter)
    shirt.data.materials.clear()
    shirt.data.materials.append(_material('Cloth_Shirt'))
    sol = shirt.modifiers.new('thickness', 'SOLIDIFY')
    sol.thickness = 0.003
    sol.offset = 1.0
    disp = shirt.modifiers.new('ease', 'DISPLACE')
    disp.strength = 0.004
    disp.mid_level = 0.0
    _only(shirt)
    for m in list(shirt.modifiers):
        bpy.ops.object.modifier_apply(modifier=m.name)

    for o in (body, shirt):
        for p in o.data.polygons:
            p.use_smooth = True
    bpy.ops.export_scene.gltf(filepath=out_glb, export_apply=True)


if __name__ == '__main__':
    main()
