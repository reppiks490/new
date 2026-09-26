from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field

from app.workers.bake_contract import HighLowBakeContract


class BakeAdapter(BaseModel):
    channel: str
    adapter: Literal['cycles_direct', 'material_emit', 'geometry_nodes_emit', 'unsupported']
    executable: bool
    requires: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class BakeAdapterPlan(BaseModel):
    adapters: list[BakeAdapter]
    blockers: list[str] = Field(default_factory=list)


def compile_bake_adapters(contract: HighLowBakeContract, *, displacement_binding: str | None = None, curvature_attribute: str | None = None, thickness_attribute: str | None = None) -> BakeAdapterPlan:
    adapters: list[BakeAdapter] = []
    blockers = list(contract.blockers)
    for channel in contract.channels:
        if channel.name in {'normal', 'ambient_occlusion'}:
            adapters.append(BakeAdapter(channel=channel.name, adapter='cycles_direct', executable=True))
        elif channel.name == 'displacement':
            ok = bool(displacement_binding)
            adapters.append(BakeAdapter(
                channel='displacement', adapter='material_emit' if ok else 'unsupported', executable=ok,
                requires=[] if ok else ['displacement_binding'],
                notes=['Bake a normalized high-resolution displacement source through an emission pass; preserve 32-bit float output.'],
            ))
        elif channel.name == 'curvature':
            ok = bool(curvature_attribute)
            adapters.append(BakeAdapter(
                channel='curvature', adapter='geometry_nodes_emit' if ok else 'unsupported', executable=ok,
                requires=[] if ok else ['curvature_attribute'],
            ))
        elif channel.name == 'thickness':
            ok = bool(thickness_attribute)
            adapters.append(BakeAdapter(
                channel='thickness', adapter='geometry_nodes_emit' if ok else 'unsupported', executable=ok,
                requires=[] if ok else ['thickness_attribute'],
            ))
    return BakeAdapterPlan(adapters=adapters, blockers=blockers)
