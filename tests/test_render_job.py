from app.render.job import compile_render_job
from app.render.output_resolution import RenderResolutionTier


def test_render_job_combines_quality_and_resolution():
    job = compile_render_job(vram_gb=24, ram_gb=64, quality_mode="hero", resolution_tier=RenderResolutionTier.UHD_8K)
    assert job.quality.name == "hero_quality"
    assert job.output.width == 7680 and job.output.height == 4320
    assert job.fits_hardware


def test_render_job_flags_16k_extreme_job_that_does_not_fit_small_hardware():
    job = compile_render_job(
        vram_gb=8, ram_gb=8, quality_mode="extreme",
        resolution_tier=RenderResolutionTier.UHD_16K, bit_depth=32,
        passes=["combined", "diffuse", "normal", "depth"],
    )
    assert not job.fits_hardware
    assert any("Consider a lower resolution_tier" in n for n in job.notes)


def test_render_job_16k_fits_on_large_hardware():
    job = compile_render_job(vram_gb=48, ram_gb=256, quality_mode="extreme", resolution_tier=RenderResolutionTier.UHD_16K)
    assert job.fits_hardware
    assert job.output.exceeds_8k
