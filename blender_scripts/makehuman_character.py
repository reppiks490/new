"""Builds a realistic base character from the CC0 MakeHuman base mesh.

    blender --background --python makehuman_character.py -- BASE_OBJ EYES_OBJ OUT_GLB

MakeHuman's base.obj and high-poly eyes (released CC0, Sept 2020; see the
header of each file) give production human topology -- 13K-quad body with
real eye sockets, lids, lips and ears -- that primitives cannot. This
script keeps only the body group (drops helper/joint proxies), converts
decimeters to meters, splits the eyes into per-eye objects with their
origins at the eyeball centre (the look-dev iris shader works in object
space), adds a refracting cornea shell per eye, and fits a simple crew-neck
shirt from the torso so portraits are clothed. Material names carry the
roles the look-dev stage keys on.
"""
from __future__ import annotations

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


def main():
    argv = sys.argv[sys.argv.index('--') + 1:]
    base_obj, eyes_obj, out_glb = argv[:3]
    bpy.ops.wm.read_factory_settings(use_empty=True)

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

    # crew-neck shirt: torso + upper-arm faces of the body, pushed out 4 mm
    lo = min(v.co.z for v in body.data.vertices)
    hi = max(v.co.z for v in body.data.vertices)
    h = hi - lo
    neck_z, hem_z = lo + h * 0.815, lo + h * 0.52
    shirt = body.copy()
    shirt.data = body.data.copy()
    shirt.name = 'Shirt'
    bpy.context.scene.collection.objects.link(shirt)
    bm = bmesh.new()
    bm.from_mesh(shirt.data)
    shoulder_half = h * 0.13
    drop = [f for f in bm.faces
            if not (hem_z < f.calc_center_median().z < neck_z and abs(f.calc_center_median().x) < shoulder_half * 1.55)]
    bmesh.ops.delete(bm, geom=drop, context='FACES')
    bm.to_mesh(shirt.data)
    bm.free()
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
