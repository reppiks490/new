from __future__ import annotations

from dataclasses import dataclass
from app.core.models import CharacterSpec, QualityTier, TextureTier
from app.providers.catalog import PROVIDERS
from app.providers.models import Capability, ProviderId, ProviderRoute, ProviderRoutingPlan


@dataclass(frozen=True)
class RouteContext:
    source_kind: str = "prompt"  # prompt | image | multiview | existing_mesh
    prioritize_portrait_fidelity: bool = True
    prioritize_printability: bool = False
    require_rigging: bool = True
    require_segmentation: bool = True


def _supports(provider: ProviderId, caps: set[Capability]) -> bool:
    return caps.issubset(PROVIDERS[provider].capabilities)


def _route(stage: str, preferred: list[ProviderId], caps: set[Capability], reasons: list[str], warnings: list[str] | None = None) -> ProviderRoute:
    valid = [p for p in preferred if _supports(p, caps)]
    if not valid:
        raise ValueError(f"No provider satisfies {stage}: {sorted(c.value for c in caps)}")
    return ProviderRoute(
        stage=stage,
        selected=valid[0],
        alternatives=valid[1:],
        reasons=reasons,
        required_capabilities=caps,
        warnings=warnings or [],
    )


def compile_provider_routing(spec: CharacterSpec, ctx: RouteContext | None = None) -> ProviderRoutingPlan:
    ctx = ctx or RouteContext()
    routes: list[ProviderRoute] = []

    # Input/generation routing.
    if ctx.source_kind == "prompt":
        routes.append(_route(
            "base_generation",
            [ProviderId.TRIPO, ProviderId.MESHY],
            {Capability.TEXT_TO_3D},
            ["Prompt-native generation; keep Hi3D API for image/multiview specialization."],
        ))
    elif ctx.source_kind == "image":
        order = [ProviderId.HI3D, ProviderId.TRIPO, ProviderId.MESHY] if ctx.prioritize_portrait_fidelity else [ProviderId.TRIPO, ProviderId.MESHY, ProviderId.HI3D]
        routes.append(_route(
            "base_generation",
            order,
            {Capability.IMAGE_TO_3D},
            ["Image-native generation; Hi3D is favored when portrait/detail specialization is requested."],
        ))
    elif ctx.source_kind == "multiview":
        routes.append(_route(
            "base_generation",
            [ProviderId.HI3D, ProviderId.TRIPO, ProviderId.MESHY],
            {Capability.MULTIVIEW_TO_3D},
            ["Multi-view reconstruction benefits from Hi3D high-resolution/portrait modes, with Tripo and Meshy as fallbacks."],
        ))

    # Extreme geometry route.
    if spec.quality_tier == QualityTier.HERO_OFFLINE or (spec.requested_triangles or 0) > 2_000_000:
        routes.append(_route(
            "extreme_geometry",
            [ProviderId.HI3D, ProviderId.TRIPO],
            {Capability.HIGH_DENSITY_2M},
            ["Hi3D documents a 5M-face 2048master target, extending beyond Tripo's 2M Ultra ceiling."],
            ["Hi3D documentation contains a 5M-vs-2M validation inconsistency; use 5M→2M retry/fallback logic."],
        ))
    else:
        routes.append(_route(
            "high_density_geometry",
            [ProviderId.TRIPO, ProviderId.HI3D],
            {Capability.HIGH_DENSITY_2M},
            ["Tripo provides a stable documented 2M Ultra interchange ceiling."],
        ))

    # Topology/post-processing route.
    routes.append(_route(
        "topology_and_remesh",
        [ProviderId.MESHY, ProviderId.TRIPO],
        {Capability.SMART_TOPOLOGY, Capability.REMESH},
        ["Meshy adds explicit Smart Topology and a 4096^3 geometry pass; Tripo remains a strong retopology fallback."],
    ))

    if spec.texture_tier == TextureTier.T8K:
        routes.append(_route(
            "texture_8k",
            [ProviderId.TRIPO, ProviderId.MESHY],
            {Capability.TEXTURE_8K, Capability.PBR},
            ["Both Tripo and Meshy document 8K PBR texture paths; retain two providers for cross-validation."],
        ))

    if ctx.require_segmentation:
        routes.append(_route(
            "semantic_segmentation",
            [ProviderId.TRIPO],
            {Capability.SEGMENTATION},
            ["Tripo exposes semantic segmentation as a dedicated API stage."],
        ))

    if ctx.require_rigging:
        routes.append(_route(
            "rigging",
            [ProviderId.TRIPO, ProviderId.MESHY],
            {Capability.RIGGING},
            ["Tripo and Meshy both expose humanoid rigging; Meshy task-id rigging requires <=300k faces."],
        ))

    if ctx.prioritize_printability:
        routes.append(_route(
            "print_preparation",
            [ProviderId.HI3D],
            {Capability.PRINT_SPLIT, Capability.MULTICOLOR_3D, Capability.PRINT_3MF},
            ["Hi3D adds dedicated split, multicolor and 3MF print-production stages absent from the core Tripo path."],
        ))

    return ProviderRoutingPlan(
        routes=routes,
        notes=[
            "Provider routing is stage-specific: no single vendor is treated as the universal best path.",
            "External APIs are optional adapters; the local Blender/USD pipeline remains the canonical integration layer.",
        ],
    )
