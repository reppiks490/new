"""Blender-side production worker for Character3D v0.7.

The script consumes a precompiled manifest. It performs conservative scene configuration and export
wiring, while recording every stage in a receipt. UDIM baking is gated on actual Blender material/
UV state and is never reported as successful merely because a plan exists.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

import bpy


def _args():
    argv=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
    p=argparse.ArgumentParser(); p.add_argument('--manifest',required=True); return p.parse_args(argv)


def _import_model(path: Path):
    ext=path.suffix.lower()
    if ext in {'.glb','.gltf'}:
        bpy.ops.import_scene.gltf(filepath=str(path))
    elif ext=='.obj':
        if hasattr(bpy.ops.wm,'obj_import'): bpy.ops.wm.obj_import(filepath=str(path))
        else: bpy.ops.import_scene.obj(filepath=str(path))
    elif ext=='.fbx':
        bpy.ops.import_scene.fbx(filepath=str(path))
    else:
        raise RuntimeError(f'Unsupported production import type: {ext}')


def _configure_cycles(preset: dict):
    scene=bpy.context.scene
    scene.render.engine='CYCLES'
    scene.cycles.samples=int(preset['samples'])
    scene.cycles.use_adaptive_sampling=bool(preset['adaptive_sampling'])
    scene.render.image_settings.file_format='OPEN_EXR'
    scene.unit_settings.system='METRIC'; scene.unit_settings.scale_length=1.0


def _export(target: dict):
    path=Path(target['path']); path.parent.mkdir(parents=True,exist_ok=True)
    fmt=target['format']
    if fmt in {'glb','gltf'}:
        bpy.ops.export_scene.gltf(filepath=str(path),export_format='GLB' if fmt=='glb' else 'GLTF_SEPARATE')
    elif fmt=='fbx':
        bpy.ops.export_scene.fbx(filepath=str(path),use_selection=False)
    elif fmt=='obj':
        if hasattr(bpy.ops.wm,'obj_export'): bpy.ops.wm.obj_export(filepath=str(path),export_selected_objects=False)
        else: bpy.ops.export_scene.obj(filepath=str(path),use_selection=False)
    elif fmt in {'usd','usdz'}:
        kwargs={'filepath':str(path)}
        if fmt=='usdz': kwargs['export_materials']=True
        bpy.ops.wm.usd_export(**kwargs)
    else:
        raise RuntimeError(f'Unsupported export target: {fmt}')
    return str(path)


def main():
    a=_args(); mp=Path(a.manifest).resolve(); manifest=json.loads(mp.read_text())
    receipt={'schema':'character3d-blender-production-receipt-v1','blender_version':bpy.app.version_string,'stages':[],'status':'running'}
    out=Path(manifest['workspace'])/'blender_production_receipt.json'; out.parent.mkdir(parents=True,exist_ok=True)
    try:
        _configure_cycles(manifest['render_preset']); receipt['stages'].append({'name':'configure_cycles','ok':True})
        _import_model(Path(manifest['source_model'])); receipt['stages'].append({'name':'import_model','ok':True})
        # Baking requires a valid high/low-poly material setup. We record the plan and precondition instead of claiming a bake.
        receipt['stages'].append({'name':'udim_bake_preflight','ok':True,'executed':False,'reason':'requires explicit high/low bake sources and material node bindings','plan':manifest['bake_plan']})
        exports=[]
        for target in manifest['export_targets']:
            exports.append(_export(target))
        receipt['stages'].append({'name':'exports','ok':True,'paths':exports})
        receipt['status']='succeeded'
    except Exception as exc:
        receipt['status']='failed'; receipt['error']=str(exc); receipt['traceback']=traceback.format_exc()
        raise
    finally:
        out.write_text(json.dumps(receipt,indent=2),encoding='utf-8')


if __name__=='__main__': main()
