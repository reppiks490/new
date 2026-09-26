from __future__ import annotations

from pathlib import Path
import numpy as np
import trimesh
from pydantic import BaseModel, Field


class ExportValidationReport(BaseModel):
    path: str
    format: str
    validator_available: bool
    parsed: bool
    geometry_count: int = 0
    face_count: int = 0
    finite_vertices: bool = False
    has_geometry: bool = False
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.validator_available and self.parsed and self.has_geometry and self.finite_vertices and not self.blockers


def validate_export(path: str | Path) -> ExportValidationReport:
    p=Path(path)
    if not p.is_file(): raise FileNotFoundError(p)
    fmt=p.suffix.lower().lstrip('.')
    if fmt in {'usd','usda','usdc','usdz'}:
        try:
            from pxr import Usd  # type: ignore
        except Exception:
            return ExportValidationReport(path=str(p),format=fmt,validator_available=False,parsed=False,warnings=['USD Python bindings are unavailable; defer structural validation to Blender/USD tooling.'])
        try:
            stage=Usd.Stage.Open(str(p))
            count=sum(1 for _ in stage.Traverse()) if stage else 0
            return ExportValidationReport(path=str(p),format=fmt,validator_available=True,parsed=stage is not None,geometry_count=count,has_geometry=count>0,finite_vertices=True,blockers=[] if count>0 else ['USD stage contains no traversable prims.'])
        except Exception as exc:
            return ExportValidationReport(path=str(p),format=fmt,validator_available=True,parsed=False,blockers=[f'USD parse failed: {exc}'])

    if fmt not in {'glb','gltf','obj','ply','stl','fbx'}:
        return ExportValidationReport(path=str(p),format=fmt,validator_available=False,parsed=False,blockers=[f'No local validator registered for .{fmt}.'])
    try:
        loaded=trimesh.load(p, force='scene', process=False)
        if isinstance(loaded,trimesh.Trimesh):
            meshes=[loaded]
        elif isinstance(loaded,trimesh.Scene):
            meshes=[g for g in loaded.geometry.values() if isinstance(g,trimesh.Trimesh)]
        else:
            meshes=[]
        verts=np.vstack([m.vertices for m in meshes]) if meshes else np.empty((0,3))
        faces=sum(len(m.faces) for m in meshes)
        finite=bool(len(verts) and np.isfinite(verts).all())
        blockers=[]
        if not meshes: blockers.append('Export contains no triangle-mesh geometry.')
        if meshes and not finite: blockers.append('Export contains non-finite vertex coordinates.')
        return ExportValidationReport(path=str(p),format=fmt,validator_available=True,parsed=True,geometry_count=len(meshes),face_count=faces,finite_vertices=finite,has_geometry=bool(meshes),blockers=blockers)
    except Exception as exc:
        return ExportValidationReport(path=str(p),format=fmt,validator_available=True,parsed=False,blockers=[f'Export parse failed: {exc}'])
