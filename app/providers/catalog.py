from __future__ import annotations

from app.providers.models import Capability, ProviderId, ProviderProfile


PROVIDERS: dict[ProviderId, ProviderProfile] = {
    ProviderId.TRIPO: ProviderProfile(
        provider=ProviderId.TRIPO,
        capabilities={
            Capability.TEXT_TO_3D,
            Capability.IMAGE_TO_3D,
            Capability.MULTIVIEW_TO_3D,
            Capability.PBR,
            Capability.TEXTURE_8K,
            Capability.HIGH_DENSITY_2M,
            Capability.SMART_TOPOLOGY,
            Capability.QUAD_OUTPUT,
            Capability.SEGMENTATION,
            Capability.RETEXTURE,
            Capability.REMESH,
            Capability.RIGGING,
            Capability.ANIMATION,
        },
        advertised_max_faces=2_000_000,
        conservative_submit_max_faces=2_000_000,
        max_texture_resolution=8192,
        notes=[
            "H3.1 documents up to 2,000,000 faces in Ultra mode.",
            "Current texture endpoint documents extreme 8K textures.",
            "Semantic mesh segmentation is available in the v2 segmentation path.",
            "Auto-rig endpoint supports 7 creature types with accurate joint placement "
            "and weight painting; a free Rig Check pre-flight call reports the "
            "recommended rig type before a paid rig is committed.",
        ],
        rig_creature_types=["biped", "quadruped", "hexapod", "octopod", "avian", "serpentine", "aquatic"],
        rig_precheck_endpoint=True,
        last_reviewed="2026-09-26",
    ),
    ProviderId.MESHY: ProviderProfile(
        provider=ProviderId.MESHY,
        capabilities={
            Capability.TEXT_TO_3D,
            Capability.IMAGE_TO_3D,
            Capability.MULTIVIEW_TO_3D,
            Capability.PBR,
            Capability.TEXTURE_8K,
            Capability.GEOMETRY_4K_PASS,
            Capability.SMART_TOPOLOGY,
            Capability.QUAD_OUTPUT,
            Capability.RETEXTURE,
            Capability.REMESH,
            Capability.UV_UNWRAP,
            Capability.RIGGING,
            Capability.ANIMATION,
        },
        advertised_max_faces=None,
        conservative_submit_max_faces=300_000,
        max_texture_resolution=8192,
        geometry_resolution_label="4096^3",
        notes=[
            "Meshy 7.1 supports a 4096^3 geometry generation pass.",
            "Remesh target_polycount is documented up to 300,000 faces.",
            "Smart Topology supports direct low-count generation with natively separated parts.",
            "Humanoid rigging requires suitably structured meshes and <=300,000 faces for task-id inputs.",
        ],
        metadata={
            "smart_topology_max_faces": 15_000,
            "smart_topology_default_faces": 4_000,
            "remesh_max_faces": 300_000,
            "uv_unwrap_max_faces": 40_000,
            "multi_image_geometry_max": "2048^3",
        },
        # Meshy's documented rigging path is task-id-based humanoid rigging (<=300k faces);
        # it does not document Tripo-style per-creature-type skeletons, so this is left empty
        # rather than assumed absent — the router should not silently ask Meshy for a
        # quadruped/avian/aquatic rig.
        rig_creature_types=[],
        last_reviewed="2026-09-26",
    ),
    ProviderId.HI3D: ProviderProfile(
        provider=ProviderId.HI3D,
        capabilities={
            Capability.IMAGE_TO_3D,
            Capability.MULTIVIEW_TO_3D,
            Capability.PBR,
            Capability.HIGH_DENSITY_2M,
            Capability.HIGH_DENSITY_5M,
            Capability.PORTRAIT_SPECIALIST,
            Capability.PRINT_SPLIT,
            Capability.MULTICOLOR_3D,
            Capability.RELIEF,
            Capability.PRINT_3MF,
            Capability.USDZ,
        },
        advertised_max_faces=5_000_000,
        conservative_submit_max_faces=2_000_000,
        geometry_resolution_label="2048^3 master",
        notes=[
            "Hi3D v3.0 documents 2048quality and 2048master generation modes.",
            "FAQ and parameter tables recommend 5,000,000 faces for 2048master.",
            "The same create-task documentation contains an older/conflicting 2,000,000-face validation error; use fallback submission logic.",
            "Hi3D adds portrait-specialized generation, model splitting, multicolor output, relief, 3MF and USDZ export.",
        ],
        metadata={"high_density_retry_ladder": [5_000_000, 2_000_000]},
        last_reviewed="2026-09-26",
    ),
}


def provider_profiles() -> list[ProviderProfile]:
    return list(PROVIDERS.values())


def providers_supporting_creature_rig(creature_type: str) -> list[ProviderId]:
    """Providers whose documented rig endpoint covers a given creature type.

    "biped" is treated as universally covered by any provider that has the
    generic RIGGING capability at all (documented humanoid rigging paths,
    e.g. Meshy's task-id rigging, don't enumerate creature types explicitly
    because they only ever mean biped/humanoid). Any other creature type
    requires a provider that explicitly enumerates it in rig_creature_types.
    """
    out: list[ProviderId] = []
    for provider_id, profile in PROVIDERS.items():
        if Capability.RIGGING not in profile.capabilities:
            continue
        if creature_type == "biped":
            out.append(provider_id)
        elif creature_type in profile.rig_creature_types:
            out.append(provider_id)
    return out


def gap_fill_capabilities() -> dict[str, list[str]]:
    """Capabilities exposed by Meshy/Hi3D that are not in the normalized Tripo profile."""
    tripo_caps = PROVIDERS[ProviderId.TRIPO].capabilities
    out: dict[str, list[str]] = {}
    for provider in (ProviderId.MESHY, ProviderId.HI3D):
        gaps = PROVIDERS[provider].capabilities - tripo_caps
        out[provider.value] = sorted(c.value for c in gaps)
    return out
