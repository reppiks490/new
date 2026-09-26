from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.materials.bake import UDIMBakePlan, compile_udim_bake_plan
from app.render.cycles import CyclesPreset, quality_preset


class ExportTarget(BaseModel):
    format: Literal['glb','gltf','obj','usd','usdz','fbx']
    path: str


class BlenderProductionManifest(BaseModel):
    schema_version: str = 'character3d-blender-production-v1'
    source_model: str
    workspace: str
    render_preset: CyclesPreset
    bake_plan: UDIMBakePlan
    export_targets: list[ExportTarget]
    require_identity_gate: bool = True
    require_specialized_qa: bool = True
    notes: list[str] = Field(default_factory=list)


def compile_blender_production_manifest(
    source_model: str | Path,
    workspace: str | Path,
    *,
    vram_gb: float,
    gpu_vendor: str='nvidia',
    render_mode: str='hero',
    udim_tiles: list[int] | None=None,
    resolution: int=8192,
    export_formats: list[str] | None=None,
) -> BlenderProductionManifest:
    source=Path(source_model)
    work=Path(workspace)
    tiles=udim_tiles or list(range(1001,1009))
    exports=export_formats or ['glb','usd']
    supported={'glb','gltf','obj','usd','usdz','fbx'}
    unknown=[x for x in exports if x not in supported]
    if unknown: raise ValueError(f'unsupported export formats: {unknown}')
    targets=[ExportTarget(format=x,path=str(work/'exports'/f'character.{x}')) for x in exports]
    return BlenderProductionManifest(
        source_model=str(source),workspace=str(work),
        render_preset=quality_preset(vram_gb,gpu_vendor=gpu_vendor,mode=render_mode),
        bake_plan=compile_udim_bake_plan(tiles,resolution=resolution,hero=render_mode in {'hero','extreme'}),
        export_targets=targets,
        notes=['Manifest compilation does not claim Blender execution; runtime worker receipts are authoritative.'],
    )


def write_blender_production_manifest(manifest: BlenderProductionManifest, path: str | Path) -> Path:
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(manifest.model_dump(mode='json'),indent=2,sort_keys=True),encoding='utf-8')
    return p
