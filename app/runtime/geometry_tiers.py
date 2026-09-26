from dataclasses import dataclass

@dataclass(frozen=True)
class GeometryTier:
    name: str
    max_triangles: int | None
    purpose: str
    nondestructive: bool

TIERS = {
    "preview": GeometryTier("preview", 100_000, "interactive authoring and web preview", False),
    "interchange_2m": GeometryTier("interchange_2m", 2_000_000, "provider interchange / high fidelity compatibility", False),
    "hero_multires": GeometryTier("hero_multires", None, "offline hero sculpt with multires + displacement", True),
}

def select_geometry_tier(*, requested_triangles: int, vram_gb: float, offline: bool = False) -> GeometryTier:
    if requested_triangles <= 100_000:
        return TIERS["preview"]
    if requested_triangles <= 2_000_000 and not offline:
        return TIERS["interchange_2m"]
    if offline and vram_gb >= 16:
        return TIERS["hero_multires"]
    return TIERS["interchange_2m"]
