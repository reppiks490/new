"""Convert the supplied clothed Command Grab source without modifying the blend.

Run from the repository root:
  blender --background --factory-startup --disable-autoexec \
    --python scripts/convert_command_grab.py

The converter retains the source rig, facial keys, outfit, props, and hair.
It deliberately does not execute embedded scripts or copy Blender lights.
"""
from __future__ import annotations

from array import array
import hashlib
import json
from pathlib import Path
import subprocess

import bpy


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'workspace/imported_models/sources/Command Grab.blend'
OUTPUT = ROOT / 'workspace/imported_models/converted/command-grab-clothed.glb'
REPORT = ROOT / 'workspace/imported_models/reports/command-grab-conversion.json'
EXPECTED_SOURCE_SHA256 = '37c35a6b63b8f29e8813f5548899e7f79b1fba0eb472607ce9e379b50bf6fad0'
CREDIT = "Fanart of wasabi_nuclear's Command Grab character; credit from supplied source."


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def topology(mesh):
    counts = array('i', [0]) * len(mesh.polygons)
    indices = array('i', [0]) * len(mesh.loops)
    mesh.polygons.foreach_get('loop_total', counts)
    mesh.loops.foreach_get('vertex_index', indices)
    return len(mesh.vertices), counts.tobytes(), indices.tobytes()


def evaluated_mesh(obj):
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get()
    return bpy.data.meshes.new_from_object(
        obj.evaluated_get(graph), preserve_all_data_layers=True, depsgraph=graph,
    )


def bake_topology_with_keys(obj):
    """Apply source smoothing/mask to every key, preserving vertex identity."""
    modifiers = [m for m in obj.modifiers if m.type != 'ARMATURE']
    if not modifiers:
        return None
    before = len(obj.data.vertices)
    modifier_names = [m.name for m in modifiers]
    arms = [m for m in obj.modifiers if m.type == 'ARMATURE']
    enabled = [(m, m.show_viewport) for m in arms]
    for m, _ in enabled:
        m.show_viewport = False
    original = obj.data.shape_keys
    metadata = [{
        'name': k.name, 'value': k.value, 'min': k.slider_min,
        'max': k.slider_max, 'relative': k.relative_key.name,
    } for k in original.key_blocks]
    if any(k.relative_key != original.key_blocks[0] for k in original.key_blocks[1:]):
        raise ValueError('Source has non-basis relative keys; conversion must be reviewed')
    for k in original.key_blocks:
        k.value = 0
    basis_mesh = evaluated_mesh(obj)
    fingerprint = topology(basis_mesh)
    coordinates = {}
    for k in original.key_blocks[1:]:
        k.value = 1
        mesh = evaluated_mesh(obj)
        if topology(mesh) != fingerprint:
            raise ValueError(f'Topology changed for {obj.name}/{k.name}')
        values = array('f', [0.0]) * (len(mesh.vertices) * 3)
        mesh.vertices.foreach_get('co', values)
        coordinates[k.name] = values
        bpy.data.meshes.remove(mesh)
        k.value = 0
    obj.data = basis_mesh
    for m in modifiers:
        obj.modifiers.remove(m)
    obj.shape_key_add(name=metadata[0]['name'], from_mix=False)
    for item in metadata[1:]:
        key = obj.shape_key_add(name=item['name'], from_mix=False)
        key.data.foreach_set('co', coordinates[item['name']])
        key.slider_min = item['min']
        key.slider_max = item['max']
        key.value = item['value']
    for m, active in enabled:
        m.show_viewport = active
    return {
        'object': obj.name, 'modifiers_baked': modifier_names,
        'vertices_before': before, 'vertices_after': len(obj.data.vertices),
        'keys_preserved': [k['name'] for k in metadata[1:]],
        'same_topology_for_every_key': True,
    }


def bake_body_color():
    """Bake the existing Blender color graph, not lighting or geometry."""
    body = bpy.data.objects['Body']
    material = body.data.materials[0]
    nodes, links = material.node_tree.nodes, material.node_tree.links
    principled = next(n for n in nodes if n.type == 'BSDF_PRINCIPLED')
    surface = next(n for n in nodes if n.type == 'OUTPUT_MATERIAL').inputs['Surface']
    color_socket = principled.inputs['Base Color'].links[0].from_socket
    texture = bpy.data.images.new('CommandGrab_BakedBaseColor', 2048, 2048, alpha=False)
    texture.colorspace_settings.name = 'sRGB'
    target = nodes.new('ShaderNodeTexImage')
    target.image = texture
    for n in nodes:
        n.select = False
    target.select = True
    nodes.active = target
    emission = nodes.new('ShaderNodeEmission')
    links.new(color_socket, emission.inputs['Color'])
    links.new(emission.outputs[0], surface)
    bpy.ops.object.select_all(action='DESELECT')
    body.hide_set(False)
    body.select_set(True)
    bpy.context.view_layer.objects.active = body
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 1
    scene.render.bake.margin = 16
    scene.render.bake.use_selected_to_active = False
    bpy.ops.object.bake(type='EMIT')
    links.new(principled.outputs[0], surface)
    links.new(target.outputs['Color'], principled.inputs['Base Color'])
    nodes.remove(emission)
    texture.pack()
    return {
        'material': material.name, 'base_color': 'Original node color result baked to 2048x2048 sRGB texture',
        'normal': 'Original connected tangent-space normal map retained',
        'limitation': 'Cycles skin subsurface scattering is not represented by core glTF PBR',
    }


def main():
    before_hash = digest(SOURCE)
    if before_hash != EXPECTED_SOURCE_SHA256:
        raise ValueError('Unexpected source revision; inspect it before conversion')
    bpy.context.preferences.filepaths.use_scripts_auto_execute = False
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE), use_scripts=False)
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    report = {
        'source': str(SOURCE.relative_to(ROOT)), 'source_sha256': before_hash,
        'output': str(OUTPUT.relative_to(ROOT)), 'blender_version': bpy.app.version_string,
        'autoexec_enabled': False,
        'source_credit': CREDIT,
        'source_texts': {t.name: t.as_string() for t in bpy.data.texts},
        'license_status': 'User-provided; source text contains attribution but no distribution license',
        'topology': [], 'hair_decimation': 'None: all source hair geometry retained',
        'excluded': ['Camera', 'Light', 'Light.001'],
    }
    # Evaluate the artist's render subdivision level, preserving all clothing.
    for obj in list(bpy.context.scene.objects):
        if obj.type != 'MESH':
            continue
        for modifier in obj.modifiers:
            if modifier.type == 'SUBSURF':
                modifier.levels = min(modifier.render_levels, 2)
        if obj.data.shape_keys:
            result = bake_topology_with_keys(obj)
            if result:
                report['topology'].append(result)
        else:
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            for modifier in list(obj.modifiers):
                if modifier.type != 'ARMATURE':
                    bpy.ops.object.modifier_apply(modifier=modifier.name)
    report['material_conversion'] = bake_body_color()
    bpy.ops.object.select_all(action='DESELECT')
    for obj in bpy.context.scene.objects:
        if obj.type in {'MESH', 'ARMATURE'}:
            obj.select_set(True)
    bpy.context.view_layer.objects.active = bpy.data.objects['Rig']
    bpy.ops.export_scene.gltf(
        filepath=str(OUTPUT), export_format='GLB', use_selection=True,
        export_apply=False, export_skins=True, export_morph=True,
        export_morph_normal=True, export_animations=False,
        export_lights=False, export_cameras=False, export_extras=False,
        export_copyright=CREDIT,
    )
    # Blender ships a separate Python; validate using the application's runtime.
    inspection = subprocess.run([
        str(ROOT / '.venv/bin/python'), '-c',
        'import json,sys; from pathlib import Path; '
        'from app.studio.model_library import inspect_model; '
        'from app.exports.gltf_validation import _load_glb; '
        'p=Path(sys.argv[1]); d,_=_load_glb(p); '
        'print(json.dumps({"inspection":inspect_model(p),'
        '"exported_joint_counts":[len(s["joints"]) for s in d.get("skins",[])],'
        '"exported_morphs":{m.get("name",str(i)):m.get("extras",{}).get("targetNames",[]) '
        'for i,m in enumerate(d["meshes"]) if m.get("weights")}}))',
        str(OUTPUT),
    ], cwd=ROOT, check=True, capture_output=True, text=True)
    report.update(json.loads(inspection.stdout))
    report['output_sha256'] = digest(OUTPUT)
    report['source_unchanged'] = digest(SOURCE) == before_hash
    if not report['source_unchanged']:
        raise AssertionError('Source changed unexpectedly')
    REPORT.write_text(json.dumps(report, indent=2) + '\n')
    print('CONVERSION_REPORT', json.dumps(report['inspection']))


if __name__ == '__main__':
    main()
