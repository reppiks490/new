from app.runtime.geometry_tiers import select_geometry_tier

def test_preview_tier():
    assert select_geometry_tier(requested_triangles=80_000, vram_gb=8).name == "preview"

def test_two_million_is_interchange():
    assert select_geometry_tier(requested_triangles=2_000_000, vram_gb=24).name == "interchange_2m"

def test_dense_offline_hero_requires_budget():
    assert select_geometry_tier(requested_triangles=8_000_000, vram_gb=24, offline=True).name == "hero_multires"
    assert select_geometry_tier(requested_triangles=8_000_000, vram_gb=8, offline=True).name == "interchange_2m"
