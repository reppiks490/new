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


def test_camera_framing_uses_real_bounding_box_center():
    mesh = _cube()
    center = (mesh.bounds[0] + mesh.bounds[1]) / 2.0
    code = mesh_to_threejs_code(mesh)
    assert f"{center[0]:.4f}" in code
    assert f"{center[1]:.4f}" in code
    assert f"{center[2]:.4f}" in code


def test_camera_far_plane_scales_with_mesh_size():
    small = trimesh.creation.box(extents=(1.0, 1.0, 1.0))
    large = trimesh.creation.box(extents=(100.0, 100.0, 100.0))
    small_code = mesh_to_threejs_code(small)
    large_code = mesh_to_threejs_code(large)

    def _far_plane(code: str) -> float:
        start = code.index("PerspectiveCamera(60, width / height, 0.1, ") + len(
            "PerspectiveCamera(60, width / height, 0.1, "
        )
        end = code.index(")", start)
        return float(code[start:end])

    assert _far_plane(large_code) > _far_plane(small_code)


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
