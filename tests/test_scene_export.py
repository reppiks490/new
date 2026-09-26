import numpy as np
import trimesh

from app.core.scene_models import AssetKind, SceneAssetInstance, SceneSpec, Transform
from app.exports.scene_export import (
    ResolvedSceneAsset,
    assemble_scene_glb,
    transform_matrix,
    validate_scene_export,
)

VALID_SHA = "b" * 64


def _write_box(path, size=1.0):
    trimesh.creation.box(extents=(size, size, size)).export(path)
    return str(path)


def _instance(iid, x=0.0):
    return SceneAssetInstance(
        instance_id=iid,
        asset_kind=AssetKind.PROP,
        asset_sha256=VALID_SHA,
        transform=Transform(position=(x, 0.0, 0.0)),
    )


def test_transform_matrix_identity_and_rotation():
    assert np.allclose(transform_matrix(Transform()), np.eye(4))
    m = transform_matrix(Transform(rotation_euler_deg=(0.0, 0.0, 90.0)))
    rotated = m @ np.array([1.0, 0.0, 0.0, 1.0])
    assert np.allclose(rotated[:3], [0.0, 1.0, 0.0], atol=1e-8)


def test_assemble_and_validate_round_trip(tmp_path):
    box_a = _write_box(tmp_path / "a.obj")
    box_b = _write_box(tmp_path / "b.obj")
    scene = SceneSpec(name="s", assets=[_instance("crate_a", x=0.0), _instance("crate_b", x=5.0)])
    resolved = [
        ResolvedSceneAsset(instance=scene.assets[0], mesh_path=box_a),
        ResolvedSceneAsset(instance=scene.assets[1], mesh_path=box_b),
    ]
    out = tmp_path / "combined.glb"

    assembled = assemble_scene_glb(scene, resolved, out)
    assert assembled.passed
    assert assembled.node_count == 2
    assert out.is_file()

    validated = validate_scene_export(scene, out)
    assert validated.passed
    assert validated.node_count == 2
    assert not validated.blockers


def test_assemble_reports_missing_resolved_mesh(tmp_path):
    box_a = _write_box(tmp_path / "a.obj")
    scene = SceneSpec(name="s", assets=[_instance("crate_a"), _instance("crate_b")])
    resolved = [ResolvedSceneAsset(instance=scene.assets[0], mesh_path=box_a)]
    out = tmp_path / "combined.glb"

    report = assemble_scene_glb(scene, resolved, out)
    assert not report.passed
    assert any("crate_b" in b for b in report.blockers)
    assert not out.exists()


def test_validate_detects_transform_mismatch(tmp_path):
    box_a = _write_box(tmp_path / "a.obj")
    scene = SceneSpec(name="s", assets=[_instance("crate_a", x=0.0)])
    resolved = [ResolvedSceneAsset(instance=scene.assets[0], mesh_path=box_a)]
    out = tmp_path / "combined.glb"
    assert assemble_scene_glb(scene, resolved, out).passed

    # Validate against a DIFFERENT declared scene (instance moved) but the same file
    # on disk -> the stored transform no longer matches what's declared.
    moved_scene = SceneSpec(name="s", assets=[_instance("crate_a", x=9.0)])
    report = validate_scene_export(moved_scene, out)
    assert not report.passed
    assert any("transform" in b for b in report.blockers)


def test_validate_detects_missing_node(tmp_path):
    box_a = _write_box(tmp_path / "a.obj")
    scene = SceneSpec(name="s", assets=[_instance("crate_a")])
    resolved = [ResolvedSceneAsset(instance=scene.assets[0], mesh_path=box_a)]
    out = tmp_path / "combined.glb"
    assemble_scene_glb(scene, resolved, out)

    scene_with_extra = SceneSpec(name="s", assets=[_instance("crate_a"), _instance("crate_missing")])
    report = validate_scene_export(scene_with_extra, out)
    assert not report.passed
    assert any("crate_missing" in b for b in report.blockers)
