import numpy as np
import pytest
import trimesh
from fastapi.testclient import TestClient

from app.core.axes import (
    YUP_TO_ZUP,
    ZUP_TO_YUP,
    export_mesh_from_zup,
    load_mesh_zup,
    resolve_up_axis,
    scene_node_matrix_for_file,
)
from app.core.scene_models import AssetKind, SceneAssetInstance, SceneSpec, Transform
from app.exports.gltf_validation import _load_glb, glb_primitive_attributes, read_glb_accessor
from app.exports.scene_export import ResolvedSceneAsset, assemble_scene_glb, validate_scene_export
from app.main import app

client = TestClient(app)


def _apex_up_zup() -> trimesh.Trimesh:
    # counter-clockwise seen from -Y ... what matters is the apex height axis
    return trimesh.Trimesh(vertices=[[0, 0, 0], [1, 0, 0], [0, 0, 5]], faces=[[0, 1, 2]], process=False)


def _raw_positions_and_indices(path):
    gltf, _ = _load_glb(path)
    prim = gltf["meshes"][0]["primitives"][0]
    positions = read_glb_accessor(path, prim["attributes"]["POSITION"]).astype(np.float64)
    indices = read_glb_accessor(path, prim["indices"]).astype(np.int64).reshape(-1, 3)
    return positions, indices


def test_conversion_is_a_proper_rotation_and_its_inverse():
    r = ZUP_TO_YUP[:3, :3]
    assert np.allclose(r @ r.T, np.eye(3))
    assert np.linalg.det(r) == pytest.approx(1.0)  # proper: winding preserved
    assert np.allclose(ZUP_TO_YUP @ YUP_TO_ZUP, np.eye(4))
    assert np.allclose(r @ [0, 0, 1], [0, 1, 0])  # Z-up height becomes glTF +Y


@pytest.mark.parametrize("path,up_axis,expected", [
    ("a.glb", "auto", "y"), ("a.GLTF", "auto", "y"), ("a.obj", "auto", "z"),
    ("a.stl", "auto", "z"), ("a.obj", "y", "y"), ("a.glb", "z", "z"),
])
def test_resolve_up_axis(path, up_axis, expected):
    assert resolve_up_axis(path, up_axis) == expected


def test_resolve_up_axis_rejects_unknown_value():
    with pytest.raises(ValueError):
        resolve_up_axis("a.glb", "x")


def test_glb_export_writes_y_up_bytes_without_mutating_the_caller_mesh(tmp_path):
    mesh = _apex_up_zup()
    before = mesh.vertices.copy()
    out = tmp_path / "apex.glb"
    export_mesh_from_zup(mesh, out)
    positions, _ = _raw_positions_and_indices(out)
    assert np.allclose(positions[2], [0, 5, 0])  # height is +Y in the file
    assert np.allclose(mesh.vertices, before)


def test_obj_export_keeps_project_z_up(tmp_path):
    out = tmp_path / "apex.obj"
    export_mesh_from_zup(_apex_up_zup(), out)
    reloaded = trimesh.load(out, force="mesh", process=False)
    assert np.allclose(reloaded.vertices[2], [0, 0, 5])


def test_provider_style_y_up_glb_loads_as_z_up(tmp_path):
    # A file that is Y-up per the glTF spec, like Tripo/Meshy/Hi3D output.
    provider_file = tmp_path / "provider.glb"
    trimesh.Trimesh(vertices=[[0, 0, 0], [1, 0, 0], [0, 5, 0]], faces=[[0, 1, 2]], process=False).export(provider_file)
    loaded = load_mesh_zup(provider_file)
    assert np.allclose(loaded.vertices[2], [0, 0, 5])


def test_glb_round_trip_is_lossless(tmp_path):
    mesh = trimesh.creation.icosphere(subdivisions=1)
    out = tmp_path / "sphere.glb"
    export_mesh_from_zup(mesh, out)
    assert np.allclose(load_mesh_zup(out).vertices, mesh.vertices, atol=1e-6)


def test_terrain_glb_from_the_api_is_y_up_and_faces_point_up_in_the_raw_file(tmp_path):
    out = tmp_path / "terrain.glb"
    r = client.post("/v1/world/terrain/generate", json={
        "terrain": {"name": "t", "size_meters": 50, "resolution_power": 4, "height_scale_meters": 12, "seed": 3},
        "output_path": str(out),
    })
    assert r.status_code == 200
    positions, indices = _raw_positions_and_indices(out)
    assert positions[:, 1].min() >= -1e-5
    assert positions[:, 1].max() <= 12 + 1e-5  # heights live on +Y
    assert np.ptp(positions[:, 0]) == pytest.approx(50, abs=1e-4)  # ground plane is X/Z
    assert np.ptp(positions[:, 2]) == pytest.approx(50, abs=1e-4)
    p0, p1, p2 = (positions[indices[:, k]] for k in range(3))
    normals = np.cross(p1 - p0, p2 - p0)
    assert (normals[:, 1] > 0).all()  # every face points up in the viewer's space


def test_world_tile_glb_from_the_api_faces_point_up_in_the_raw_file(tmp_path):
    out = tmp_path / "tile.glb"
    r = client.post("/v1/world/tile/generate", json={
        "world": {"name": "w", "world_resolution_power": 5, "tile_count_x": 2, "tile_count_z": 2,
                  "tile_size_meters": 40, "height_scale_meters": 15, "seed": 2},
        "tile_x": 1, "tile_z": 0, "output_path": str(out),
    })
    assert r.status_code == 200
    positions, indices = _raw_positions_and_indices(out)
    p0, p1, p2 = (positions[indices[:, k]] for k in range(3))
    assert (np.cross(p1 - p0, p2 - p0)[:, 1] > 0).all()


def test_scene_node_matrix_is_conjugated_only_for_gltf():
    t = np.eye(4)
    t[:3, 3] = [1, 2, 3]  # Z-up world: 3 m up
    assert np.allclose(scene_node_matrix_for_file(t, "scene.obj"), t)
    m = scene_node_matrix_for_file(t, "scene.glb")
    assert np.allclose(m[:3, 3], [1, 3, -2])  # the same point, expressed Y-up


def test_provider_character_stands_upright_on_terrain_in_an_exported_scene(tmp_path):
    # 2 m tall character, Y-up like every provider GLB.
    character = tmp_path / "character.glb"
    trimesh.creation.box(extents=(0.5, 2.0, 0.3)).export(character)
    # 40 m wide, flat-ish terrain tile written through the project's exporter.
    terrain = tmp_path / "terrain.glb"
    export_mesh_from_zup(trimesh.creation.box(extents=(40.0, 40.0, 0.2)), terrain)

    sha = "c" * 64
    scene = SceneSpec(name="s", assets=[
        SceneAssetInstance(instance_id="ground", asset_kind=AssetKind.ENVIRONMENT, asset_sha256=sha,
                           transform=Transform(position=(0.0, 0.0, 0.0))),
        SceneAssetInstance(instance_id="hero", asset_kind=AssetKind.PROP, asset_sha256=sha,
                           transform=Transform(position=(3.0, 4.0, 1.1))),  # Z-up: 1.1 m up
    ])
    out = tmp_path / "scene.glb"
    report = assemble_scene_glb(scene, [
        ResolvedSceneAsset(instance=scene.assets[0], mesh_path=str(terrain)),
        ResolvedSceneAsset(instance=scene.assets[1], mesh_path=str(character)),
    ], out)
    assert report.passed
    assert validate_scene_export(scene, out).passed

    # World space as any glTF viewer sees it (trimesh applies node transforms
    # on load and does no axis conversion of its own).
    loaded = trimesh.load(out, force="scene", process=False)
    hero_matrix, hero_key = loaded.graph["hero"]
    hero_world = trimesh.transform_points(loaded.geometry[hero_key].vertices, hero_matrix)
    ground_matrix, ground_key = loaded.graph["ground"]
    ground_world = trimesh.transform_points(loaded.geometry[ground_key].vertices, ground_matrix)

    hero_extents = np.ptp(hero_world, axis=0)
    assert hero_extents[1] == pytest.approx(2.0, abs=1e-5)  # upright: tall along glTF +Y
    assert np.ptp(ground_world, axis=0)[1] == pytest.approx(0.2, abs=1e-5)  # ground lies flat
    assert hero_world[:, 1].mean() == pytest.approx(1.1, abs=1e-5)  # declared height, on the up axis


def test_body_morph_height_slider_scales_the_real_vertical_axis_of_a_provider_glb(tmp_path):
    source = tmp_path / "character.glb"
    trimesh.creation.box(extents=(0.5, 2.0, 0.3)).export(source)  # Y-up, 2 m tall
    out = tmp_path / "taller.glb"
    r = client.post("/v1/body-morphs/apply", json={
        "input_path": str(source), "output_path": str(out), "percentages": {"height": 50},
    })
    assert r.status_code == 200, r.text
    positions, _ = _raw_positions_and_indices(out)
    extents = np.ptp(positions, axis=0)
    assert extents[1] > 2.0  # taller along the file's real up axis
    assert extents[0] == pytest.approx(0.5, abs=1e-5)  # width untouched
    assert extents[2] == pytest.approx(0.3, abs=1e-5)  # depth untouched


def test_glb_primitive_attributes_lists_position():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "a.glb"
        export_mesh_from_zup(_apex_up_zup(), path)
        assert "POSITION" in glb_primitive_attributes(path)
