from __future__ import annotations
from pydantic import BaseModel, Field

class BakePass(BaseModel):
    map_kind: str
    bit_depth: int
    color_space: str
    margin_px: int
    samples: int

class UDIMBakePlan(BaseModel):
    resolution: int
    tiles: list[int]
    passes: list[BakePass]
    estimated_raw_gib: float
    notes: list[str]=Field(default_factory=list)


def compile_udim_bake_plan(tiles: list[int], *, resolution: int=8192, hero: bool=True) -> UDIMBakePlan:
    if resolution not in {2048,4096,8192}: raise ValueError('resolution must be 2K, 4K or 8K')
    if not tiles or any(t<1001 or t>1999 for t in tiles): raise ValueError('invalid UDIM tile list')
    passes=[
      BakePass(map_kind='basecolor',bit_depth=16 if hero else 8,color_space='sRGB',margin_px=32,samples=256),
      BakePass(map_kind='normal',bit_depth=16,color_space='Non-Color',margin_px=32,samples=512),
      BakePass(map_kind='roughness',bit_depth=16 if hero else 8,color_space='Non-Color',margin_px=32,samples=256),
      BakePass(map_kind='displacement',bit_depth=32 if hero else 16,color_space='Non-Color',margin_px=48,samples=1024),
      BakePass(map_kind='ao',bit_depth=16 if hero else 8,color_space='Non-Color',margin_px=32,samples=512),
    ]
    raw=sum(resolution*resolution*(p.bit_depth/8)*(3 if p.map_kind in {'basecolor','normal'} else 1) for p in passes)*len(tiles)/(1024**3)
    return UDIMBakePlan(resolution=resolution,tiles=sorted(set(tiles)),passes=passes,estimated_raw_gib=round(raw,3),notes=['Raw estimate excludes compression, mipmaps and temporary bake buffers.'])
