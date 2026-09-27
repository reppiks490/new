"""Builds a crude stand-in head (skin, sclera, cornea, shirt materials) for look-dev tests."""
import bpy, bmesh
bpy.ops.wm.read_factory_settings(use_empty=True)
def mat(n): return bpy.data.materials.new(n)
def add(obj, m): obj.data.materials.append(m)
bpy.ops.mesh.primitive_uv_sphere_add(segments=96, ring_count=64, radius=0.1, location=(0,0,1.62))
h=bpy.context.object; h.name='Head'; h.scale=(0.78,0.95,1.18); add(h, mat('Skin_Face'))
bpy.ops.object.shade_smooth()
bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=0.045, location=(0,0.01,1.49))
n=bpy.context.object; n.name='Neck'; n.scale=(1,1,2.2); add(n, h.data.materials[0])
for x in (-0.032, 0.032):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=32, radius=0.012, location=(x,-0.078,1.65))
    e=bpy.context.object; add(e, mat('Eye_Sclera'))
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=32, radius=0.0125, location=(x,-0.078,1.65))
    c=bpy.context.object; add(c, mat('Cornea_Wet'))
bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=0.14, depth=0.12, location=(0,0.01,1.33))
s=bpy.context.object; s.name='Shirt'; add(s, mat('Cloth_Shirt'))
bpy.ops.export_scene.gltf(filepath=__import__('sys').argv[-1])
