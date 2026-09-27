"""Localized Blender repair worker for Character3D v0.9.

This worker is intentionally conservative. It duplicates the source object, expands the directly
intersecting face selection by a small number of adjacency rings, deletes the selected patch, fills
its boundary, triangulates the replacement, recalculates normals, and exports a separate candidate.
The original source is never overwritten. Acceptance is performed outside Blender by identity and
exact-intersection gates.
"""
from __future__ import annotations
import argparse, json, sys, traceback
from pathlib import Path
import bpy, bmesh
from mathutils.bvhtree import BVHTree


def _args():
    argv = sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
    p=argparse.ArgumentParser(); p.add_argument('--contract', required=True); return p.parse_args(argv)


def _import(path: Path):
    before=set(bpy.data.objects)
    ext=path.suffix.lower()
    if ext in {'.glb','.gltf'}: bpy.ops.import_scene.gltf(filepath=str(path))
    elif ext=='.fbx': bpy.ops.import_scene.fbx(filepath=str(path))
    elif ext=='.obj':
        (bpy.ops.wm.obj_import if hasattr(bpy.ops.wm,'obj_import') else bpy.ops.import_scene.obj)(filepath=str(path))
    elif ext=='.ply': bpy.ops.wm.ply_import(filepath=str(path))
    else: raise RuntimeError(f'unsupported repair source: {ext}')
    meshes=[o for o in bpy.data.objects if o not in before and o.type=='MESH']
    if len(meshes)!=1: raise RuntimeError('localized repair requires one imported mesh object')
    return meshes[0]


def _export(obj, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action='DESELECT'); obj.select_set(True); bpy.context.view_layer.objects.active=obj
    ext=path.suffix.lower()
    if ext in {'.glb','.gltf'}: bpy.ops.export_scene.gltf(filepath=str(path), export_format='GLB' if ext=='.glb' else 'GLTF_SEPARATE', use_selection=True)
    elif ext=='.fbx': bpy.ops.export_scene.fbx(filepath=str(path), use_selection=True)
    elif ext=='.obj':
        if hasattr(bpy.ops.wm,'obj_export'): bpy.ops.wm.obj_export(filepath=str(path), export_selected_objects=True)
        else: bpy.ops.export_scene.obj(filepath=str(path), use_selection=True)
    elif ext=='.ply': bpy.ops.wm.ply_export(filepath=str(path), export_selected_objects=True)
    else: raise RuntimeError(f'unsupported repair output: {ext}')


def _intersecting_faces(bm) -> tuple[set[int], int]:
    """Self-intersecting faces in Blender's own polygon index space. Face
    indices from another tool (trimesh triangulates quads; importers split
    or reorder faces) do not survive import, so the repair never trusts
    them -- applying triangle indices to a quad mesh deletes the wrong
    faces. BVHTree self-overlap ignores neighbours that merely share a
    vertex or edge."""
    bm.faces.ensure_lookup_table()
    tree = BVHTree.FromBMesh(bm)
    pairs = [(a, b) for a, b in tree.overlap(tree) if a != b]
    return {i for pair in pairs for i in pair}, len({tuple(sorted(pr)) for pr in pairs})


def _edge_components(edges):
    remaining, components = set(edges), []
    while remaining:
        stack, comp = [remaining.pop()], []
        while stack:
            e = stack.pop()
            comp.append(e)
            for v in e.verts:
                for other in v.link_edges:
                    if other in remaining:
                        remaining.remove(other)
                        stack.append(other)
        components.append(comp)
    return components


def _repair(obj, contract_faces, rings, index_space):
    mesh = obj.data
    bm = bmesh.new(); bm.from_mesh(mesh); bm.faces.ensure_lookup_table()
    detected, detected_pairs = _intersecting_faces(bm)
    if index_space == 'blender_polygons':
        seed = {i for i in contract_faces if 0 <= i < len(bm.faces)}
    else:
        seed = detected
    if not seed:
        raise RuntimeError('no self-intersecting faces found in the imported mesh (Blender BVH self-overlap)')
    selected = {bm.faces[i] for i in seed}
    for _ in range(rings):
        selected |= {f for face in tuple(selected) for e in face.edges for f in e.link_faces}
    removed = len(selected)
    # Only fill holes this repair cuts. Filling every boundary edge also caps
    # an open mesh's own borders (terrain, cloth, planes), stacking large
    # coplanar faces on top of the surface -- invisible to BVH overlap, which
    # ignores coplanar contact, but real overlapping geometry.
    for e in bm.edges:
        e.tag = e.is_boundary
    bmesh.ops.delete(bm, geom=list(selected), context='FACES')
    boundary = [e for e in bm.edges if e.is_boundary and not e.tag]
    input_was_closed = not any(e.tag for e in bm.edges)
    created, filled_loops, open_chains = [], 0, 0
    for loop in _edge_components(boundary):
        degree = {}
        for e in loop:
            for v in e.verts:
                degree[v] = degree.get(v, 0) + 1
        if any(d != 2 for d in degree.values()):
            # an open chain that runs into the mesh's original border (e.g. a
            # strip cut across a plane): there is no hole to close
            open_chains += 1
            continue
        # holes_fill silently skips long/non-planar loops (verified on a
        # 24-edge loop in Blender 5.0); contextual_create closes each loop.
        faces = bmesh.ops.contextual_create(bm, geom=loop)['faces']
        if faces:
            filled_loops += 1
            created.extend(faces)
    if created:
        created = bmesh.ops.triangulate(bm, faces=created, quad_method='BEAUTY', ngon_method='BEAUTY')['faces']
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    remaining_faces, remaining_pairs = _intersecting_faces(bm)
    boundary_after = sum(1 for e in bm.edges if e.is_boundary)
    bm.to_mesh(mesh); mesh.update(); bm.free()
    return {
        'detected_faces': len(detected), 'detected_pairs': detected_pairs,
        'affected_faces': removed, 'created_faces': len(created),
        'filled_hole_loops': filled_loops, 'open_boundary_chains': open_chains,
        'input_was_closed': input_was_closed,
        'boundary_edges_after': boundary_after,
        'remaining_intersecting_faces': len(remaining_faces), 'remaining_intersecting_pairs': remaining_pairs,
    }


def _start_clean_scene():
    # Blender's startup scene carries a default cube/camera/light that would
    # otherwise be exported (and baked) alongside the real asset. A .blend
    # passed on the command line is the intended scene and is kept.
    if not bpy.data.filepath:
        bpy.ops.wm.read_factory_settings(use_empty=True)


def main():
    a=_args(); contract=json.loads(Path(a.contract).read_text()); receipt={'schema':'character3d-localized-repair-receipt-v1','status':'running','source_mesh':contract['source_mesh'],'blender_version':bpy.app.version_string}
    _start_clean_scene()
    out=Path(a.contract).with_name('localized_repair_receipt.json')
    try:
        if contract.get('blockers'): raise RuntimeError('; '.join(contract['blockers']))
        obj=_import(Path(contract['source_mesh']))
        stats=_repair(obj, contract['affected_faces'], int(contract.get('boundary_rings',1)), contract.get('face_index_space','detect_in_blender'))
        target=Path(contract['output_mesh']); _export(obj,target)
        receipt.update({'status':'succeeded','output_mesh':str(target),'contract_face_count':len(contract['affected_faces']),**stats})
    except Exception as exc:
        receipt.update({'status':'failed','error':str(exc),'traceback':traceback.format_exc()}); raise
    finally:
        out.write_text(json.dumps(receipt,indent=2),encoding='utf-8')

if __name__=='__main__': main()
