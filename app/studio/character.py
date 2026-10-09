import numpy as np
import trimesh
from app.studio.parameters import CharacterState, human_data
from app.studio.wardrobe import catalog, garment_mask


def build_character(state: CharacterState) -> trimesh.Scene:
    data = human_data()
    vertices = np.array(data['positions'], dtype=float)
    for delta in data['bases'][state.base]:
        d = np.array(delta)
        vertices[d[:, 0].astype(int)] += d[:, 1:] / 3
    for control in data['controls']:
        value = state.controls.get(control['id'], 0)
        if not value:
            continue
        d = np.array(control['positive' if value > 0 else 'negative'])
        vertices[d[:, 0].astype(int)] += d[:, 1:] * abs(value)/100
    mesh = trimesh.Trimesh(vertices=vertices, faces=np.array(data['indices']).reshape(-1, 3), process=False)
    mesh.visual = trimesh.visual.ColorVisuals(mesh, vertex_colors=trimesh.visual.color.hex_to_rgba(state.skin))
    scene = trimesh.Scene()
    scene.add_geometry(mesh, node_name='CC0_Adult_Base_Static', geom_name='body')
    item = next((c for c in catalog() if c['id'] == state.outfit), None)
    if item is None:
        raise ValueError('Unknown outfit')
    mask = garment_mask(mesh.triangles_center, mesh.bounds, item)
    normals = mesh.vertex_normals
    cloth = trimesh.Trimesh(vertices=vertices + normals*.0035, faces=mesh.faces[mask], process=False)
    cloth.visual = trimesh.visual.ColorVisuals(cloth, vertex_colors=trimesh.visual.color.hex_to_rgba(state.cloth))
    scene.add_geometry(cloth, node_name=item['id'], geom_name='garment')
    for side, indices in data['eyes'].items():
        center = vertices[indices].mean(axis=0)
        radius = np.linalg.norm(vertices[indices]-center, axis=1).mean() * .83
        eye = trimesh.creation.icosphere(subdivisions=2, radius=radius)
        eye.apply_translation(center)
        eye.visual.vertex_colors = [230, 232, 218, 255]
        scene.add_geometry(eye, node_name=f'eye-{side}')
    scene.metadata = {'source': data['source'], 'license': data['license'],
                      'rigged': False, 'outfit_construction': 'procedural surface shell',
                      'extreme_combinations_validated': False}
    return scene
