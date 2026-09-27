from __future__ import annotations

"""Final render OUTPUT resolution -- distinct from texture/bake resolution
(app/qa/textures.py, app/materials/). The goal spec explicitly separates
these two things; this module is the render-output half. Tiers double the
same way this project's existing texture tiers already do (2K/4K/8K), and
go one step past 8K to an explicit "exceeding 8K" tier per the requested
scope.
"""

from enum import Enum

from pydantic import BaseModel, Field


class RenderResolutionTier(str, Enum):
    HD = "hd"
    QHD = "2k"
    UHD_4K = "4k"
    UHD_8K = "8k"
    UHD_16K = "16k"  # exceeds 8K
    UHD_32K = "32k"  # rendered in horizontal strips (app/render/cycles_worker.py)


RESOLUTIONS: dict[RenderResolutionTier, tuple[int, int]] = {
    RenderResolutionTier.HD: (1920, 1080),
    RenderResolutionTier.QHD: (2560, 1440),
    RenderResolutionTier.UHD_4K: (3840, 2160),
    RenderResolutionTier.UHD_8K: (7680, 4320),
    RenderResolutionTier.UHD_16K: (15360, 8640),
    RenderResolutionTier.UHD_32K: (30720, 17280),
}


class RenderOutputSpec(BaseModel):
    tier: RenderResolutionTier
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    overscan_px: int = Field(default=0, ge=0)
    # 32-bit float is the real EXR-class depth for hero/extreme offline
    # renders; 16-bit half-float and 8-bit are also valid for lower tiers.
    bit_depth: int = Field(default=16, ge=8, le=32)
    passes: list[str] = Field(default_factory=lambda: ["combined"])

    @property
    def full_width(self) -> int:
        return self.width + 2 * self.overscan_px

    @property
    def full_height(self) -> int:
        return self.height + 2 * self.overscan_px

    @property
    def exceeds_8k(self) -> bool:
        return max(self.width, self.height) > RESOLUTIONS[RenderResolutionTier.UHD_8K][0]


def render_output_spec_for_tier(
    tier: RenderResolutionTier,
    *,
    overscan_px: int = 0,
    bit_depth: int = 16,
    passes: list[str] | None = None,
) -> RenderOutputSpec:
    width, height = RESOLUTIONS[tier]
    return RenderOutputSpec(
        tier=tier, width=width, height=height,
        overscan_px=overscan_px, bit_depth=bit_depth,
        passes=passes or ["combined"],
    )


def estimate_render_buffer_gib(spec: RenderOutputSpec, *, channels_per_pass: int = 4) -> float:
    """Raw in-memory render buffer size across all requested passes/AOVs.
    Same budgeting-estimate discipline as app/materials/udim.py and
    app/materials/bake.py -- a staging-memory estimate, not compressed
    disk size, and it excludes denoiser feature buffers and the render
    engine's own working memory."""
    bytes_per_pixel_per_pass = channels_per_pass * (spec.bit_depth / 8)
    total_bytes = spec.full_width * spec.full_height * bytes_per_pixel_per_pass * len(spec.passes)
    return total_bytes / (1024 ** 3)


def render_fits_hardware(spec: RenderOutputSpec, *, ram_gb: float, headroom_ratio: float = 0.5) -> tuple[bool, list[str]]:
    """Conservative fit check: render buffers should not be allowed to claim
    more than `headroom_ratio` of available system RAM, leaving room for
    scene geometry, textures, and the render engine itself. Mirrors the
    hardware-aware capping already used for geometry
    (app/pipeline/planner.py::_hardware_hero_cap) and world tiling
    (app/pipeline/scene_planner.py::_hardware_scene_cap), applied to render
    output buffers instead."""
    if ram_gb <= 0:
        raise ValueError("ram_gb must be positive")
    estimated = estimate_render_buffer_gib(spec)
    budget = ram_gb * headroom_ratio
    notes: list[str] = []
    fits = estimated <= budget
    if not fits:
        notes.append(
            f"Estimated render buffer ({estimated:.2f} GiB across {len(spec.passes)} pass(es)) "
            f"exceeds the conservative {headroom_ratio:.0%} RAM budget ({budget:.2f} GiB of {ram_gb:.1f} GiB). "
            "Reduce pass count, bit depth, or render in tiles."
        )
    if spec.exceeds_8k:
        notes.append(
            f"{spec.width}x{spec.height} exceeds 8K; tiled/bucketed rendering and denoising are "
            "strongly recommended regardless of estimated fit."
        )
    return fits, notes
