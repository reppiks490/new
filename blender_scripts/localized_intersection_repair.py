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


def _repair(obj, face_indices, rings):
    mesh=obj.data; bm=bmesh.new(); bm.from_mesh(mesh); bm.faces.ensure_lookup_table()
    selected={bm.faces[i] for i in face_indices if 0 <= i < len(bm.faces)}
    if not selected: raise RuntimeError('contract selected no valid faces')
    for _ in range(rings):
        selected |= {f for face in tuple(selected) for e in face.edges for f in e.link_faces}
    bmesh.ops.delete(bm, geom=list(selected), context='FACES')
    boundary=[e for e in bm.edges if len(e.link_faces)==1]
    created=[]
    if boundary:
        result=bmesh.ops.holes_fill(bm, edges=boundary, sides=0)
        created=[g for g in result.get('faces',[]) if isinstance(g,bmesh.types.BMFace)]
        if created: bmesh.ops.triangulate(bm, faces=created)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh); mesh.update(); bm.free()
    return len(selected), len(created)


def main():
    a=_args(); contract=json.loads(Path(a.contract).read_text()); receipt={'schema':'character3d-localized-repair-receipt-v1','status':'running','source_mesh':contract['source_mesh'],'blender_version':bpy.app.version_string}
    out=Path(a.contract).with_name('localized_repair_receipt.json')
    try:
        if contract.get('blockers'): raise RuntimeError('; '.join(contract['blockers']))
        obj=_import(Path(contract['source_mesh']))
        affected, created=_repair(obj, contract['affected_faces'], int(contract.get('boundary_rings',1)))
        target=Path(contract['output_mesh']); _export(obj,target)
        receipt.update({'status':'succeeded','output_mesh':str(target),'affected_faces':affected,'created_faces':created})
    except Exception as exc:
        receipt.update({'status':'failed','error':str(exc),'traceback':traceback.format_exc()}); raise
    finally:
        out.write_text(json.dumps(receipt,indent=2),encoding='utf-8')

if __name__=='__main__': main()
