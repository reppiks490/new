from __future__ import annotations

import math
from app.core.models import (
    CharacterSpec,
    HardwareProfile,
    QualityTier,
    TextureTier,
    GeometryPlan,
    MaterialPlan,
    PipelinePlan,
)
from app.core.policy import evaluate_policy
from app.providers.router import RouteContext, compile_provider_routing


TIER_DEFAULTS = {
    QualityTier.PREVIEW: (100_000, 250_000, 500_000),
    QualityTier.PRODUCTION: (250_000, 750_000, 2_000_000),
    QualityTier.COMPAT_2M: (500_000, 2_000_000, 8_000_000),
    QualityTier.HERO_OFFLINE: (750_000, 2_000_000, 32_000_000),
}

TEXTURE_RES = {
    TextureTier.T2K: 2048,
    TextureTier.T4K: 4096,
    TextureTier.T8K: 8192,
}

CHANNELS = [
    "baseColor",
    "normal",
    "roughness",
    "metallic",
    "displacement",
    "subsurface",
    "microNormal",
]


def _hardware_hero_cap(hw: HardwareProfile) -> int:
    # Conservative planning cap, not a hard engine limit. Dense source meshes are for sculpt/bake,
    # not necessarily for interactive animation. RAM and VRAM both constrain practical workflows.
    ram_cap = int(hw.ram_gb * 1_000_000)
    vram_cap = int(hw.vram_gb * 1_500_000)
    return max(2_000_000, min(100_000_000, ram_cap, vram_cap))


def geometry_plan(spec: CharacterSpec, hw: HardwareProfile) -> GeometryPlan:
    viewport, interchange, hero = TIER_DEFAULTS[spec.quality_tier]
    hero = min(hero, _hardware_hero_cap(hw))
    if spec.requested_triangles:
        hero = min(spec.requested_triangles, _hardware_hero_cap(hw))
        interchange = min(interchange, hero)
        viewport = min(viewport, interchange)

    ratio = max(1, hero // max(1, viewport))
    subdivision_levels = max(0, min(8, math.ceil(math.log(ratio, 4))))
    notes = [
        "Keep a deformation-friendly base mesh separate from dense hero/source geometry.",
        "Bake dense sculpt detail into displacement/normal maps for downstream efficiency.",
    ]
    if spec.quality_tier == QualityTier.HERO_OFFLINE:
        notes.append("Hero density is a planning target; actual safe density is hardware- and scene-dependent.")

    return GeometryPlan(
        viewport_triangles=viewport,
        interchange_triangles=interchange,
        hero_source_triangles=hero,
        subdivision_levels=subdivision_levels,
        bake_required=hero > interchange,
        notes=notes,
    )


def material_plan(spec: CharacterSpec) -> MaterialPlan:
    res = TEXTURE_RES[spec.texture_tier]
    # Approximate raw storage: RGB/RGBA channels averaged to 4 bytes/pixel/channel group.
    # This is a budgeting estimate; compression and bit depth vary per channel.
    bytes_per_tile = res * res * 4 * len(CHANNELS)
    gib = bytes_per_tile * spec.udim_tiles / (1024**3)
    return MaterialPlan(
        resolution=res,
        udim_tiles=spec.udim_tiles,
        channels=CHANNELS,
        estimated_uncompressed_gib=round(gib, 3),
        notes=[
            "Use 16/32-bit displacement where required; actual disk/VRAM use can exceed this estimate.",
            "Stream or page UDIM tiles rather than forcing all 8K maps resident at once.",
        ],
    )


def compile_plan(spec: CharacterSpec, hw: HardwareProfile) -> PipelinePlan:
    policy = evaluate_policy(spec)
    if not policy.allowed:
        return PipelinePlan(policy=policy)

    stages = [
        "prompt_spec",
        "base_character",
        "hero_geometry",
        "retopo_uv_lod",
        "materials_udim",
        "skin_eyes_hair",
        "rig_morph_correctives",
        "animation_pose",
        "render_preview",
        "render_offline",
        "export_validation",
    ]
    provider_plan = compile_provider_routing(spec, RouteContext(source_kind="prompt"))
    return PipelinePlan(
        policy=policy,
        geometry=geometry_plan(spec, hw),
        materials=material_plan(spec),
        stages=stages,
        provider_routes=[r.model_dump(mode="json") for r in provider_plan.routes],
    )
