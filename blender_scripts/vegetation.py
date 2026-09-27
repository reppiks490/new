"""Procedural 3D vegetation for the Cycles render worker.

Trees are real geometry -- tapered trunks, limbs and thousands of separate
leaf quads with gaps between them, so light and the camera see through the
canopy -- built once per variant and instanced, which is why tens of
thousands of trees cost almost no memory. Placement samples the exported
vegetation map (same biome weights that paint the ground) at each point's
UV, and each tree is lifted by the displacement map so it stands on the
rendered surface, not on the coarse base grid.
"""
from __future__ import annotations

import math

import bmesh
import bpy
import numpy as np


# 4x leaves at half the edge length: same canopy coverage, finer silhouette
# and more, smaller gaps. Instanced, so this costs unique geometry only.
LEAF_DETAIL = 4
VARIANTS = 12  # distinct meshes per species; repetition is invisible at 16K


def _leaf_material(name: str, base: tuple[float, float, float]):
    mat = bpy.data.materials.new(name)
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    info = nt.nodes.new('ShaderNodeObjectInfo')
    ramp = nt.nodes.new('ShaderNodeValToRGB')  # per-tree tint variation
    ramp.color_ramp.elements[0].color = (*[c * 0.7 for c in base], 1)
    ramp.color_ramp.elements[1].color = (*[min(1.0, c * 1.25) for c in base], 1)
    bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.inputs['Roughness'].default_value = 0.55
    translucent = nt.nodes.new('ShaderNodeBsdfTranslucent')
    mix = nt.nodes.new('ShaderNodeMixShader')
    mix.inputs['Fac'].default_value = 0.3  # backlit leaves glow
    nt.links.new(info.outputs['Random'], ramp.inputs['Fac'])
    nt.links.new(ramp.outputs['Color'], bsdf.inputs['Base Color'])
    nt.links.new(ramp.outputs['Color'], translucent.inputs['Color'])
    nt.links.new(bsdf.outputs[0], mix.inputs[1])
    nt.links.new(translucent.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs['Surface'])
    return mat


def _bark_material():
    mat = bpy.data.materials.new('C3D_Bark')
    bsdf = mat.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = (0.09, 0.06, 0.04, 1)
    bsdf.inputs['Roughness'].default_value = 0.9
    return mat


def _cylinder(bm, p0, p1, r0, r1, sides=8):
    axis = np.asarray(p1, float) - np.asarray(p0, float)
    length = np.linalg.norm(axis)
    if length < 1e-6:
        return
    z = axis / length
    x = np.cross(z, [0, 0, 1] if abs(z[2]) < 0.9 else [1, 0, 0])
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    rings = []
    for center, r in ((p0, r0), (p1, r1)):
        ring = []
        for k in range(sides):
            a = 2 * math.pi * k / sides
            ring.append(bm.verts.new(tuple(np.asarray(center) + r * (math.cos(a) * x + math.sin(a) * y))))
        rings.append(ring)
    for k in range(sides):
        bm.faces.new((rings[0][k], rings[0][(k + 1) % sides], rings[1][(k + 1) % sides], rings[1][k]))


def _leaf(bm, center, size, rng):
    n = rng.normal(size=3)
    n /= np.linalg.norm(n)
    t = np.cross(n, [0, 0, 1] if abs(n[2]) < 0.9 else [1, 0, 0])
    t /= np.linalg.norm(t)
    b = np.cross(n, t)
    c = np.asarray(center)
    w, h = size * 0.5, size
    quad = [c - t * w, c + b * h * 0.5, c + t * w, c - b * h * 0.5]
    bm.faces.new([bm.verts.new(tuple(p)) for p in quad])


def build_conifer(name, seed, bark, leaves):
    rng = np.random.default_rng(seed)
    bm = bmesh.new()
    _cylinder(bm, (0, 0, 0), (0, 0, 1.0), 0.03, 0.004)
    tiers = 16
    for i in range(tiers):
        zf = 0.18 + 0.8 * i / tiers
        reach = 0.32 * (1.0 - (zf - 0.18) / 0.82) + 0.03
        for k in range(7):
            a = 2 * math.pi * (k / 7 + rng.uniform(-0.05, 0.05)) + i * 0.7
            d = np.array([math.cos(a), math.sin(a), -0.25])
            for s in np.linspace(0.15, 1.0, 9 * LEAF_DETAIL):
                p = np.array([0, 0, zf]) + d * reach * s + rng.normal(scale=0.012, size=3)
                if rng.random() < 0.85:  # gaps: the canopy stays see-through
                    _leaf(bm, p, 0.045 / LEAF_DETAIL ** 0.5, rng)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    mesh.materials.append(bark)
    mesh.materials.append(leaves)
    ncyl = 8  # the first faces are the trunk
    for poly in mesh.polygons:
        poly.material_index = 0 if poly.index < ncyl else 1
    return mesh


def build_broadleaf(name, seed, bark, leaves):
    rng = np.random.default_rng(seed)
    bm = bmesh.new()
    _cylinder(bm, (0, 0, 0), (0, 0, 0.45), 0.035, 0.02)
    trunk_faces = 8
    tips = []
    for k in range(6):
        a = 2 * math.pi * k / 6 + rng.uniform(-0.3, 0.3)
        tip = np.array([math.cos(a) * rng.uniform(0.18, 0.3), math.sin(a) * rng.uniform(0.18, 0.3), rng.uniform(0.62, 0.85)])
        _cylinder(bm, (0, 0, 0.4), tuple(tip), 0.016, 0.006, sides=6)
        trunk_faces += 6
        tips.append(tip)
    tips.append(np.array([0, 0, 0.9]))
    for tip in tips:
        for _ in range(420 * LEAF_DETAIL):
            offset = rng.normal(size=3) * np.array([0.13, 0.13, 0.1])
            if np.linalg.norm(offset / np.array([0.13, 0.13, 0.1])) < 2.2:
                _leaf(bm, tip + offset, 0.05 / LEAF_DETAIL ** 0.5, rng)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    mesh.materials.append(bark)
    mesh.materials.append(leaves)
    for poly in mesh.polygons:
        poly.material_index = 0 if poly.index < trunk_faces else 1
    return mesh


def _tree_collection(kind, count, seed):
    bark = _bark_material()
    coll = bpy.data.collections.new(f'C3D_Trees_{kind}')
    bpy.context.scene.collection.children.link(coll)
    coll.hide_render = True  # only the instances render
    tris = 0
    for v in range(count):
        if kind == 'conifer':
            mesh = build_conifer(f'conifer_{v}', seed + v, bark, _leaf_material(f'C3D_Needles_{v}', (0.05, 0.16, 0.06)))
        else:
            mesh = build_broadleaf(f'broadleaf_{v}', seed + 100 + v, bark, _leaf_material(f'C3D_Leaves_{v}', (0.12, 0.26, 0.05)))
        obj = bpy.data.objects.new(mesh.name, mesh)
        coll.objects.link(obj)
        tris += sum(len(p.vertices) - 2 for p in mesh.polygons)
    return coll, tris


def _scatter_group(name, terrain, veg_img, disp, channel, density, collection, height_range, seed):
    ng = bpy.data.node_groups.new(name, 'GeometryNodeTree')
    ng.interface.new_socket('Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    ng.interface.new_socket('Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    N, L = ng.nodes, ng.links
    out = N.new('NodeGroupOutput')
    src = N.new('GeometryNodeObjectInfo')
    src.inputs['Object'].default_value = terrain
    src.transform_space = 'RELATIVE'
    uv_face = N.new('GeometryNodeInputNamedAttribute')
    uv_face.data_type = 'FLOAT_VECTOR'
    uv_face.inputs['Name'].default_value = terrain.data.uv_layers.active.name
    veg = N.new('GeometryNodeImageTexture')
    veg.inputs['Image'].default_value = veg_img
    sep = N.new('FunctionNodeSeparateColor')
    dens = N.new('ShaderNodeMath')
    dens.operation = 'MULTIPLY'
    dens.inputs[1].default_value = density
    dist = N.new('GeometryNodeDistributePointsOnFaces')
    dist.distribute_method = 'RANDOM'
    dist.inputs['Seed'].default_value = seed
    L.new(uv_face.outputs['Attribute'], veg.inputs['Vector'])
    L.new(veg.outputs['Color'], sep.inputs['Color'])
    L.new(sep.outputs[channel], dens.inputs[0])
    L.new(src.outputs['Geometry'], dist.inputs['Mesh'])
    L.new(dens.outputs[0], dist.inputs['Density'])

    # lift each point onto the displaced surface
    uv_pt = N.new('GeometryNodeInputNamedAttribute')
    uv_pt.data_type = 'FLOAT_VECTOR'
    uv_pt.inputs['Name'].default_value = uv_face.inputs['Name'].default_value
    dtex = N.new('GeometryNodeImageTexture')
    dtex.inputs['Image'].default_value = bpy.data.images.load(disp['path'], check_existing=True)
    dtex.interpolation = 'Cubic'
    decode = N.new('ShaderNodeMath')
    decode.operation = 'MULTIPLY_ADD'
    decode.inputs[1].default_value = disp['max_m'] - disp['min_m']
    decode.inputs[2].default_value = disp['min_m']
    lift = N.new('ShaderNodeCombineXYZ')
    setpos = N.new('GeometryNodeSetPosition')
    L.new(uv_pt.outputs['Attribute'], dtex.inputs['Vector'])
    L.new(dtex.outputs['Color'], decode.inputs[0])
    L.new(decode.outputs[0], lift.inputs['Z'])
    L.new(dist.outputs['Points'], setpos.inputs['Geometry'])
    L.new(lift.outputs['Vector'], setpos.inputs['Offset'])

    coll = N.new('GeometryNodeCollectionInfo')
    coll.inputs['Collection'].default_value = collection
    coll.inputs['Separate Children'].default_value = True
    coll.inputs['Reset Children'].default_value = True
    pick = N.new('FunctionNodeRandomValue')
    pick.data_type = 'INT'
    pick.inputs['Min'].default_value = 0
    pick.inputs['Max'].default_value = len(collection.objects) - 1
    pick.inputs['Seed'].default_value = seed + 1
    spin = N.new('FunctionNodeRandomValue')
    spin.data_type = 'FLOAT_VECTOR'
    spin.inputs['Min'].default_value = (0, 0, 0)
    spin.inputs['Max'].default_value = (0.06, 0.06, 2 * math.pi)
    spin.inputs['Seed'].default_value = seed + 2
    size = N.new('FunctionNodeRandomValue')
    size.data_type = 'FLOAT'
    size.inputs['Min'].default_value = height_range[0]
    size.inputs['Max'].default_value = height_range[1]
    size.inputs['Seed'].default_value = seed + 3
    inst = N.new('GeometryNodeInstanceOnPoints')
    inst.inputs['Pick Instance'].default_value = True
    L.new(setpos.outputs['Geometry'], inst.inputs['Points'])
    L.new(coll.outputs['Instances'], inst.inputs['Instance'])
    L.new(pick.outputs[2], inst.inputs['Instance Index'])
    L.new(spin.outputs[0], inst.inputs['Rotation'])
    L.new(size.outputs[1], inst.inputs['Scale'])
    L.new(inst.outputs['Instances'], out.inputs['Geometry'])
    return ng


def scatter_vegetation(terrain, disp: dict, veg: dict, seed: int = 7) -> dict:
    veg_img = bpy.data.images.load(veg['path'])
    veg_img.colorspace_settings.name = 'Non-Color'
    conifers, t1 = _tree_collection('conifer', VARIANTS, seed)
    broadleaves, t2 = _tree_collection('broadleaf', VARIANTS, seed)
    holder_mesh = bpy.data.meshes.new('C3D_Vegetation')
    holder = bpy.data.objects.new('C3D_Vegetation', holder_mesh)
    bpy.context.scene.collection.objects.link(holder)
    holder.matrix_world = terrain.matrix_world
    groups = [
        _scatter_group('C3D_Forest', terrain, veg_img, disp, 'Red', veg['forest_density_per_m2'] * 0.6, conifers, (13, 24), seed),
        _scatter_group('C3D_ForestBroad', terrain, veg_img, disp, 'Red', veg['forest_density_per_m2'] * 0.4, broadleaves, (10, 18), seed + 10),
        _scatter_group('C3D_Plains', terrain, veg_img, disp, 'Green', veg['plains_density_per_m2'], broadleaves, (8, 15), seed + 20),
    ]
    join_tree = bpy.data.node_groups.new('C3D_VegetationAll', 'GeometryNodeTree')
    join_tree.interface.new_socket('Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    join_tree.interface.new_socket('Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    join = join_tree.nodes.new('GeometryNodeJoinGeometry')
    jout = join_tree.nodes.new('NodeGroupOutput')
    for g in groups:
        node = join_tree.nodes.new('GeometryNodeGroup')
        node.node_tree = g
        join_tree.links.new(node.outputs[0], join.inputs[0])
    join_tree.links.new(join.outputs[0], jout.inputs[0])
    mod = holder.modifiers.new('C3D_Vegetation', 'NODES')
    mod.node_group = join_tree
    depsgraph = bpy.context.evaluated_depsgraph_get()
    instances = sum(1 for inst in depsgraph.object_instances if inst.is_instance and inst.parent and inst.parent.name == holder.name)
    tris_per_variant = (t1 + t2) / (2 * VARIANTS)
    return {'instances': instances, 'unique_tree_triangles': t1 + t2,
            'effective_triangles': int(instances * tris_per_variant)}
