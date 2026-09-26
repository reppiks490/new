from __future__ import annotations

from pydantic import BaseModel, Field


class UDIMTilePlan(BaseModel):
    tile: int
    region: str
    resolution: int
    channels: list[str]


class UDIMPlan(BaseModel):
    resolution: int
    tiles: list[UDIMTilePlan]
    estimated_uncompressed_gib: float
    estimated_half_float_gib: float
    notes: list[str] = Field(default_factory=list)


def plan_character_udims(tile_count: int = 8, *, resolution: int = 8192, channels: list[str] | None = None) -> UDIMPlan:
    if not 1 <= tile_count <= 100:
        raise ValueError("tile_count must be 1..100")
    if resolution not in {2048, 4096, 8192}:
        raise ValueError("resolution must be 2048, 4096, or 8192")
    channels = channels or ["base_color", "normal", "roughness", "metallic", "displacement", "subsurface"]
    regions = ["face", "head", "torso", "arms_hands", "legs_feet", "eyes_mouth", "hair_scalp", "accessories"]
    tiles = [UDIMTilePlan(tile=1001 + i, region=regions[i] if i < len(regions) else f"extra_{i+1}", resolution=resolution, channels=channels) for i in range(tile_count)]
    # Conservative RGBA32 estimate: 4 bytes/channel pixel per map. This is staging memory, not compressed disk size.
    raw_bytes = tile_count * len(channels) * resolution * resolution * 4
    half_float_bytes = tile_count * len(channels) * resolution * resolution * 8
    gib = raw_bytes / (1024 ** 3)
    hf = half_float_bytes / (1024 ** 3)
    notes = ["Streaming/virtual-texture strategies are required for large 8K UDIM sets; do not assume all tiles remain resident on the GPU."]
    if resolution == 8192 and tile_count >= 8:
        notes.append("Hero 8K UDIM configuration: use mip streaming and bake per region to avoid VRAM spikes.")
    return UDIMPlan(resolution=resolution, tiles=tiles, estimated_uncompressed_gib=round(gib, 4), estimated_half_float_gib=round(hf, 4), notes=notes)
