import pytest

from app.core.models import HardwareProfile
from app.core.scene_models import AssetKind, SceneAssetInstance, SceneScale, SceneSpec, Transform
from app.pipeline.scene_planner import compile_scene_plan, scene_manifest_hash
from app.qa.scene import qa_scene_placement

VALID_SHA = "a" * 64


def _instance(iid, x=0.0, radius=None, viewport=1000, hero=5000):
    return SceneAssetInstance(
        instance_id=iid,
        asset_kind=AssetKind.CHARACTER,
        asset_sha256=VALID_SHA,
        transform=Transform(position=(x, 0.0, 0.0)),
        viewport_triangles=viewport,
        hero_source_triangles=hero,
        bounding_radius_m=radius,
    )


def test_scene_rejects_duplicate_instance_ids():
    with pytest.raises(ValueError):
        SceneSpec(name="s", assets=[_instance("a"), _instance("a")])


def test_transform_rejects_zero_scale_and_non_finite_values():
    with pytest.raises(ValueError):
        Transform(scale=(0.0, 1.0, 1.0))
    with pytest.raises(ValueError):
        Transform(position=(float("nan"), 0.0, 0.0))


def test_scene_budget_sums_across_assets_and_flags_overbudget():
    scene = SceneSpec(
        name="crowd",
        scale=SceneScale.OPEN_WORLD,
        assets=[_instance(f"c{i}", x=float(i), hero=50_000_000) for i in range(5)],
    )
    plan = compile_scene_plan(scene, HardwareProfile(vram_gb=8, ram_gb=16))
    assert plan.budget.instance_count == 5
    assert plan.budget.total_hero_triangles == 250_000_000
    assert plan.budget.over_budget
    assert plan.warnings
    assert "scene_assembly_blender" in plan.stages


def test_scene_manifest_hash_is_deterministic_and_change_sensitive():
    a = SceneSpec(name="s", assets=[_instance("a")])
    b = SceneSpec(name="s", assets=[_instance("a")])
    assert scene_manifest_hash(a) == scene_manifest_hash(b)
    c = SceneSpec(name="s", assets=[_instance("a", x=1.0)])
    assert scene_manifest_hash(a) != scene_manifest_hash(c)


def test_scene_placement_detects_overlap_and_out_of_bounds():
    scene = SceneSpec(
        name="s",
        bounds_meters=(4.0, 4.0, 4.0),
        assets=[
            _instance("a", x=0.0, radius=1.0),
            _instance("b", x=1.0, radius=1.0),  # overlaps a
            _instance("c", x=100.0, radius=0.5),  # outside declared bounds
        ],
    )
    report = qa_scene_placement(scene)
    assert ("a", "b") in report.overlapping_pairs
    assert "c" in report.out_of_bounds
    assert not report.passed


def test_scene_placement_passes_clean_layout():
    scene = SceneSpec(
        name="s",
        bounds_meters=(20.0, 20.0, 20.0),
        assets=[_instance("a", x=0.0, radius=0.5), _instance("b", x=5.0, radius=0.5)],
    )
    report = qa_scene_placement(scene)
    assert report.passed
    assert not report.overlapping_pairs
    assert not report.out_of_bounds
