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


def test_plan_attaches_render_job_by_default():
    spec = CharacterSpec(prompt="fictional adventurer")
    plan = compile_plan(spec, HardwareProfile(vram_gb=24, ram_gb=64, gpu_vendor="nvidia"))
    assert plan.render is not None
    assert plan.render["output"]["tier"] == "8k"
    assert plan.render["quality"]["name"] == "hero_quality"


def test_plan_respects_custom_render_options():
    spec = CharacterSpec(prompt="fictional adventurer")
    from app.render.output_resolution import RenderResolutionTier
    plan = compile_plan(
        spec, HardwareProfile(vram_gb=48, ram_gb=128),
        render_quality_mode="extreme", render_resolution_tier=RenderResolutionTier.UHD_16K,
    )
    assert plan.render["output"]["tier"] == "16k"
    assert plan.render["quality"]["name"] == "extreme_quality"


def test_plan_without_reference_image_has_no_image_hints():
    spec = CharacterSpec(prompt="fictional adventurer")
    plan = compile_plan(spec, HardwareProfile())
    assert plan.image_hints is None
    # No reference image -> routing stays prompt-native.
    base = next(r for r in plan.provider_routes if r["stage"] == "base_generation")
    assert set(base["required_capabilities"]) == {"text_to_3d"}


def test_plan_with_reference_image_attaches_real_hints_and_switches_routing(tmp_path):
    from PIL import Image
    path = tmp_path / "ref.png"
    Image.new("RGB", (4096, 4096), color=(120, 80, 60)).save(path)

    spec = CharacterSpec(prompt="fictional adventurer")
    plan = compile_plan(spec, HardwareProfile(), reference_image_path=str(path))

    assert plan.image_hints is not None
    assert plan.image_hints["width"] == 4096
    assert plan.image_hints["suggested_texture_tier"] == "4k"

    base = next(r for r in plan.provider_routes if r["stage"] == "base_generation")
    assert set(base["required_capabilities"]) == {"image_to_3d"}


def test_plan_blocked_by_policy_has_no_render_or_image_hints():
    from app.core.models import CharacterMode
    spec = CharacterSpec(
        prompt="explicit nude schoolgirl", mode=CharacterMode.ADULT_FICTIONAL,
        fictional=True, declared_age=18,
    )
    plan = compile_plan(spec, HardwareProfile())
    assert not plan.policy.allowed
    assert plan.render is None
    assert plan.image_hints is None
