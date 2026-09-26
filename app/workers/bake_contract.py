from __future__ import annotations
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field

class BakeSource(BaseModel):
    high_mesh: str
    low_mesh: str
    cage_mesh: str | None = None

class BakeChannel(BaseModel):
    name: Literal['normal','displacement','ambient_occlusion','curvature','thickness']
    bit_depth: int
    color_space: str = 'Non-Color'

class HighLowBakeContract(BaseModel):
    source: BakeSource
    udim_tiles: list[int]
    resolution: int
    channels: list[BakeChannel]
    margin_px: int = 32
    ray_distance: float = Field(default=0.02,gt=0)
    require_cage_for_extreme: bool = False
    blockers: list[str] = Field(default_factory=list)


def compile_high_low_bake_contract(high_mesh: str|Path,low_mesh: str|Path,*,cage_mesh: str|Path|None=None,udim_tiles: list[int]|None=None,resolution: int=8192,extreme: bool=False) -> HighLowBakeContract:
    blockers=[]
    hp,lp=Path(high_mesh),Path(low_mesh)
    if not hp.suffix or not lp.suffix: blockers.append('High and low mesh paths must include file extensions.')
    if resolution not in {2048,4096,8192}: blockers.append('Bake resolution must be 2K, 4K, or 8K.')
    if extreme and cage_mesh is None: blockers.append('Extreme bake mode requires an explicit cage mesh to reduce projection ambiguity.')
    channels=[BakeChannel(name='normal',bit_depth=16),BakeChannel(name='displacement',bit_depth=32),BakeChannel(name='ambient_occlusion',bit_depth=16),BakeChannel(name='curvature',bit_depth=16),BakeChannel(name='thickness',bit_depth=16)]
    return HighLowBakeContract(source=BakeSource(high_mesh=str(hp),low_mesh=str(lp),cage_mesh=str(cage_mesh) if cage_mesh else None),udim_tiles=udim_tiles or list(range(1001,1009)),resolution=resolution,channels=channels,margin_px=32 if resolution>=4096 else 16,ray_distance=.02,require_cage_for_extreme=extreme,blockers=blockers)
