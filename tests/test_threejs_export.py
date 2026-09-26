import json

import numpy as np
import pytest
import trimesh

from app.viz.threejs_export import mesh_to_threejs_code


def _cube():
    return trimesh.creation.box(extents=(2.0, 4.0, 6.0))


def test_generates_nonempty_code_for_simple_mesh():
    code = mesh_to_threejs_code(_cube())
    assert "THREE.BufferGeometry" in code
    assert "THREE.Mesh" in code
    assert "OrbitControls" in code


def test_positions_and_indices_are_valid_json_arrays_embedded_in_js():
    mesh = _cube()
    code = mesh_to_threejs_code(mesh)
    positions_start = code.index("Float32BufferAttribute([") + len("Float32BufferAttribute([") - 1
    positions_end = code.index("], 3));", positions_start) + 1
    positions = json.loads(code[positions_start:positions_end])
    assert len(positions) == len(mesh.vertices) * 3

    indices_start = code.index("setIndex([") + len("setIndex([") - 1
    indices_end = code.index("]);", indices_start) + 1
    indices = json.loads(code[indices_start:indices_end])
    assert len(indices) == len(mesh.faces) * 3


def _positions(code: str) -> np.ndarray:
    start = code.index("Float32BufferAttribute([") + len("Float32BufferAttribute([") - 1
    end = code.index("], 3));", start) + 1
    return np.asarray(json.loads(code[start:end])).reshape(-1, 3)


def _clip_planes(code: str) -> tuple[float, float]:
    start = code.index("PerspectiveCamera(50, width / height, ") + len("PerspectiveCamera(50, width / height, ")
    end = code.index(")", start)
    near, far = (float(x) for x in code[start:end].split(","))
    return near, far


def _camera_position(code: str) -> np.ndarray:
    start = code.index("camera.position.set(") + len("camera.position.set(")
    end = code.index(");", start)
    # each component is "center + distance * factor"
    values = []
    for part in code[start:end].split(","):
        base, scaled = part.split("+")
        distance, factor = scaled.split("*")
        values.append(float(base) + float(distance) * float(factor))
    return np.array(values)


def test_camera_target_is_the_y_up_bounding_box_center():
    mesh = trimesh.Trimesh(vertices=[[0, 0, 0], [10, 0, 0], [0, 20, 30]], faces=[[0, 1, 2]], process=False)
    code = mesh_to_threejs_code(mesh)  # default: input is Z-up
    # Z-up (x, y, z) -> Y-up (x, z, -y): bounds x[0,10], y[0,30], z[-20,0]
    assert "controls.target.set(5.0000, 15.0000, -10.0000)" in code


def test_z_up_input_is_rotated_so_height_becomes_three_js_y():
    apex_up = trimesh.Trimesh(vertices=[[0, 0, 0], [1, 0, 0], [0, 0, 5]], faces=[[0, 1, 2]], process=False)
    positions = _positions(mesh_to_threejs_code(apex_up))
    assert np.allclose(positions[2], [0, 5, 0])


def test_y_up_input_is_passed_through_unrotated():
    apex_up = trimesh.Trimesh(vertices=[[0, 0, 0], [1, 0, 0], [0, 5, 0]], faces=[[0, 1, 2]], process=False)
    positions = _positions(mesh_to_threejs_code(apex_up, up_axis="y"))
    assert np.allclose(positions[2], [0, 5, 0])


def test_camera_is_above_the_mesh_in_y_up_space():
    from app.world.terrain import TerrainSpec, generate_terrain_mesh

    terrain = generate_terrain_mesh(TerrainSpec(name="t", size_meters=100, resolution_power=3, height_scale_meters=20))
    code = mesh_to_threejs_code(terrain)
    top_of_terrain = _positions(code)[:, 1].max()
    assert _camera_position(code)[1] > top_of_terrain


def test_rejects_unknown_up_axis():
    with pytest.raises(ValueError):
        mesh_to_threejs_code(_cube(), up_axis="x")


def test_clip_planes_scale_with_mesh_size():
    small_near, small_far = _clip_planes(mesh_to_threejs_code(trimesh.creation.box(extents=(1.0, 1.0, 1.0))))
    large_near, large_far = _clip_planes(mesh_to_threejs_code(trimesh.creation.box(extents=(1000.0, 1000.0, 1000.0))))
    assert large_far > small_far
    assert large_near > small_near
    # depth-buffer ratio stays bounded instead of growing with mesh size
    assert large_far / large_near == pytest.approx(small_far / small_near, rel=1e-3)


def test_vertex_colors_are_converted_from_srgb_to_linear():
    mesh = _cube()
    mesh.visual.vertex_colors = np.tile([128, 128, 128, 255], (len(mesh.vertices), 1)).astype(np.uint8)
    code = mesh_to_threejs_code(mesh)
    start = code.index("setAttribute('color', new THREE.Float32BufferAttribute(") + len(
        "setAttribute('color', new THREE.Float32BufferAttribute("
    )
    end = code.index("], 3));", start) + 1
    colors = json.loads(code[start:end])
    # sRGB 128/255 is ~0.2158 linear, not 0.502
    assert colors[0] == pytest.approx(0.21586, abs=1e-4)


def test_rejects_non_finite_vertices():
    mesh = _cube()
    mesh.vertices[0, 0] = float("nan")
    with pytest.raises(ValueError, match="non-finite"):
        mesh_to_threejs_code(mesh)


def test_rejects_empty_mesh():
    empty = trimesh.Trimesh(vertices=np.zeros((0, 3)), faces=np.zeros((0, 3), dtype=int))
    with pytest.raises(ValueError, match="no geometry"):
        mesh_to_threejs_code(empty)


def test_no_vertex_color_attribute_when_mesh_has_no_vertex_colors():
    mesh = _cube()
    # TextureVisuals has no vertex_colors attribute at all, unlike ColorVisuals
    # (which always synthesizes a default gray) -- this is the real "no vertex
    # colors" case the export function's getattr(..., None) check guards against.
    mesh.visual = trimesh.visual.TextureVisuals()
    code = mesh_to_threejs_code(mesh)
    assert "setAttribute('color'" not in code
    assert "vertexColors: true" not in code


def test_vertex_color_attribute_present_when_mesh_has_vertex_colors():
    mesh = _cube()
    mesh.visual.vertex_colors = np.tile([255, 0, 0, 255], (len(mesh.vertices), 1)).astype(np.uint8)
    code = mesh_to_threejs_code(mesh)
    assert "setAttribute('color'" in code
    assert "vertexColors: true" in code


def test_wireframe_flag_is_reflected_in_material():
    code = mesh_to_threejs_code(_cube(), wireframe=True)
    assert "wireframe: true" in code
    code_off = mesh_to_threejs_code(_cube(), wireframe=False)
    assert "wireframe: false" in code_off


def test_background_and_material_color_hex_are_embedded():
    mesh = _cube()
    mesh.visual = trimesh.visual.TextureVisuals()  # no vertex colors -> material_color_hex is used
    code = mesh_to_threejs_code(mesh, background_hex=0x112233, material_color_hex=0x445566)
    assert hex(0x112233) in code
    assert hex(0x445566) in code
