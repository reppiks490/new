from pathlib import Path
import pytest
from app.packs.manager import PackRegistry, CapabilityPack


def registry() -> PackRegistry:
    return PackRegistry.from_yaml(Path(__file__).parents[1] / "config" / "packs" / "registry.yaml")


def test_full_quality_pack_budget_exceeds_real_gigabyte_scale():
    reg = registry()
    ids = ["reconstruction_hq", "upscale_detail", "groom_pro", "motion_studio", "render_studio", "environments_hq"]
    assert reg.expected_size_gb(ids) > 80


def test_dependencies_are_deduplicated_and_ordered():
    reg = registry()
    resolved = reg.resolve(["motion_studio", "reconstruction_hq"])
    ids = [p.id for p in resolved]
    assert ids.count("core_runtime") == 1
    assert ids.index("geometry_base") < ids.index("rig_pro")


def test_cycle_detection():
    a = CapabilityPack(id="a", name="a", category="core", version="1", expected_size_gb=1, description="", dependencies=["b"])
    b = CapabilityPack(id="b", name="b", category="core", version="1", expected_size_gb=1, description="", dependencies=["a"])
    with pytest.raises(ValueError):
        PackRegistry([a,b]).resolve(["a"])
