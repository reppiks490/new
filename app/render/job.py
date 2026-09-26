from __future__ import annotations

from pydantic import BaseModel, Field

from app.render.cycles import CyclesPreset, quality_preset
from app.render.output_resolution import (
    RenderOutputSpec,
    RenderResolutionTier,
    render_fits_hardware,
    render_output_spec_for_tier,
)


class RenderJobSpec(BaseModel):
    """Ties sampling/denoise quality (CyclesPreset -- "how good") together
    with output resolution (RenderOutputSpec -- "how big"), which previously
    existed as two entirely separate, unconnected modules."""
    quality: CyclesPreset
    output: RenderOutputSpec
    fits_hardware: bool
    notes: list[str] = Field(default_factory=list)


def compile_render_job(
    *,
    vram_gb: float,
    ram_gb: float,
    gpu_vendor: str = "nvidia",
    quality_mode: str = "hero",
    resolution_tier: RenderResolutionTier = RenderResolutionTier.UHD_8K,
    overscan_px: int = 0,
    bit_depth: int = 16,
    passes: list[str] | None = None,
) -> RenderJobSpec:
    quality = quality_preset(vram_gb, gpu_vendor=gpu_vendor, mode=quality_mode)
    output = render_output_spec_for_tier(resolution_tier, overscan_px=overscan_px, bit_depth=bit_depth, passes=passes)
    fits, notes = render_fits_hardware(output, ram_gb=ram_gb)
    if not fits:
        notes = notes + [f"Consider a lower resolution_tier or fewer passes for a {quality_mode!r} job on {ram_gb:.0f} GiB RAM."]
    return RenderJobSpec(quality=quality, output=output, fits_hardware=fits, notes=notes)
