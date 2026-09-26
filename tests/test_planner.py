from app.core.models import CharacterSpec, HardwareProfile, QualityTier, TextureTier
from app.pipeline.planner import compile_plan


def test_compat_2m_plan():
    spec = CharacterSpec(prompt="fictional adult hero character", quality_tier=QualityTier.COMPAT_2M)
    plan = compile_plan(spec, HardwareProfile(vram_gb=24, ram_gb=64, gpu_vendor="nvidia"))
    assert plan.geometry is not None
    assert plan.geometry.interchange_triangles == 2_000_000
    assert plan.geometry.hero_source_triangles >= 2_000_000


def test_8k_udim_budget_positive():
    spec = CharacterSpec(prompt="fictional character", texture_tier=TextureTier.T8K, udim_tiles=8)
    plan = compile_plan(spec, HardwareProfile())
    assert plan.materials is not None
    assert plan.materials.resolution == 8192
    assert plan.materials.estimated_uncompressed_gib > 0
