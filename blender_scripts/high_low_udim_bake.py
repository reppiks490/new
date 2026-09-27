"""Blender 4.x selected-to-active UDIM bake worker for Character3D v0.8.

Executes real NORMAL and AO high->low baking when high/low objects are importable and low has UVs.
Displacement/curvature/thickness remain source-dependent channels and are reported as unexecuted unless
explicit material bindings are provided by a future adapter. The receipt is authoritative.
"""
from __future__ import annotations
import argparse, json, sys, traceback
from pathlib import Path
import bpy


def args():
    argv=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
    p=argparse.ArgumentParser(); p.add_argument('--contract',required=True); p.add_argument('--workspace',required=True); return p.parse_args(argv)


def import_model(path: Path, prefix: str):
    before=set(bpy.data.objects)
    ext=path.suffix.lower()
    if ext in {'.glb','.gltf'}: bpy.ops.import_scene.gltf(filepath=str(path))
    elif ext=='.fbx': bpy.ops.import_scene.fbx(filepath=str(path))
    elif ext=='.obj':
        (bpy.ops.wm.obj_import if hasattr(bpy.ops.wm,'obj_import') else bpy.ops.import_scene.obj)(filepath=str(path))
    else: raise RuntimeError(f'unsupported bake source: {ext}')
    created=[o for o in bpy.data.objects if o not in before and o.type=='MESH']
    if not created: raise RuntimeError(f'no mesh objects imported from {path}')
    for i,o in enumerate(created): o.name=f'{prefix}_{i:03d}'
    return created


def ensure_udim_image(low, name: str, resolution: int, tiles: list[int]):
    if not low.data.uv_layers: raise RuntimeError('low mesh has no UV layer')
    img=bpy.data.images.new(name,width=resolution,height=resolution,tiled=True,float_buffer=name.endswith('_displacement'))
    existing={t.number for t in img.tiles}
    for tile in tiles:
        if tile not in existing: img.tiles.new(tile_number=tile)
    mat=low.data.materials[0] if low.data.materials else bpy.data.materials.new(name=f'{low.name}_BAKE')
    if not low.data.materials: low.data.materials.append(mat)
    mat.use_nodes=True; nodes=mat.node_tree.nodes
    node=nodes.new('ShaderNodeTexImage'); node.name=f'CHARACTER3D_BAKE_{name}'; node.image=img; node.interpolation='Linear'
    nodes.active=node
    return img


def bake_selected_to_active(highs, low, channel: str, image, workspace: Path, margin: int, cage=None, ray_distance=.02):
    bpy.ops.object.select_all(action='DESELECT')
    for o in highs: o.select_set(True)
    low.select_set(True); bpy.context.view_layer.objects.active=low
    scene=bpy.context.scene; scene.render.engine='CYCLES'; scene.render.bake.use_selected_to_active=True; scene.render.bake.margin=margin
    scene.render.bake.max_ray_distance=ray_distance
    if cage:
        scene.render.bake.use_cage=True; scene.render.bake.cage_object=cage
    bake_type={'normal':'NORMAL','ambient_occlusion':'AO'}.get(channel)
    if not bake_type: return {'channel':channel,'executed':False,'reason':'source-dependent bake channel requires explicit binding'}
    bpy.ops.object.bake(type=bake_type)
    out=workspace/'bakes'; out.mkdir(parents=True,exist_ok=True)
    # Blender tiled images save one file per tile when filepath contains <UDIM>.
    image.filepath_raw=str(out/f'{channel}.<UDIM>.exr'); image.file_format='OPEN_EXR'; image.save()
    return {'channel':channel,'executed':True,'filepath':image.filepath_raw}


def _start_clean_scene():
    # Blender's startup scene carries a default cube/camera/light that would
    # otherwise be exported (and baked) alongside the real asset. A .blend
    # passed on the command line is the intended scene and is kept.
    if not bpy.data.filepath:
        bpy.ops.wm.read_factory_settings(use_empty=True)


def main():
    a=args(); contract=json.loads(Path(a.contract).read_text()); workspace=Path(a.workspace); receipt={'schema':'character3d-high-low-bake-receipt-v1','status':'running','channels':[],'blender_version':bpy.app.version_string}
    _start_clean_scene()
    out=workspace/'high_low_bake_receipt.json'; out.parent.mkdir(parents=True,exist_ok=True)
    try:
        if contract.get('blockers'): raise RuntimeError('bake contract has blockers: '+ '; '.join(contract['blockers']))
        src=contract['source']; highs=import_model(Path(src['high_mesh']),'HIGH'); lows=import_model(Path(src['low_mesh']),'LOW'); low=lows[0]
        cage=None
        if src.get('cage_mesh'): cage=import_model(Path(src['cage_mesh']),'CAGE')[0]
        for ch in contract['channels']:
            img=ensure_udim_image(low,ch['name'],int(contract['resolution']),list(contract['udim_tiles']))
            receipt['channels'].append(bake_selected_to_active(highs,low,ch['name'],img,workspace,int(contract['margin_px']),cage,float(contract['ray_distance'])))
        receipt['status']='succeeded'
    except Exception as exc:
        receipt['status']='failed'; receipt['error']=str(exc); receipt['traceback']=traceback.format_exc(); raise
    finally:
        out.write_text(json.dumps(receipt,indent=2),encoding='utf-8')

if __name__=='__main__': main()
