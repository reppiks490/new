from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import trimesh
from pydantic import BaseModel, Field


class MeshQAReport(BaseModel):
    path: str
    format: str
    face_count: int
    vertex_count: int
    geometry_count: int
    body_count: int
    watertight: bool
    winding_consistent: bool
    degenerate_face_count: int
    degenerate_face_ratio: float = Field(ge=0, le=1)
    uv_vertex_ratio: float = Field(ge=0, le=1)
    surface_area: float
    bounds_min: tuple[float, float, float]
    bounds_max: tuple[float, float, float]
    extents: tuple[float, float, float]
    warnings: list[str] = Field(default_factory=list)

    @property
    def healthy_for_refinement(self) -> bool:
        return self.face_count > 0 and self.degenerate_face_ratio < 0.01 and self.winding_consistent


def _scene_from_file(path: Path) -> trimesh.Scene:
    loaded = trimesh.load(path, force="scene", process=False)
    if isinstance(loaded, trimesh.Trimesh):
        scene = trimesh.Scene()
        scene.add_geometry(loaded)
        return scene
    if not isinstance(loaded, trimesh.Scene):
        raise ValueError(f"Unsupported mesh payload: {type(loaded)!r}")
    return loaded


def _degenerate_count(mesh: trimesh.Trimesh) -> int:
    try:
        mask = mesh.nondegenerate_faces()
        return int(len(mask) - int(np.count_nonzero(mask)))
    except Exception:
        # Conservative fallback: repeated vertex indices are definitely degenerate.
        faces = np.asarray(mesh.faces)
        if faces.size == 0:
            return 0
        repeated = (faces[:, 0] == faces[:, 1]) | (faces[:, 1] == faces[:, 2]) | (faces[:, 0] == faces[:, 2])
        return int(np.count_nonzero(repeated))


def _uv_ratio(mesh: trimesh.Trimesh) -> float:
    uv = getattr(getattr(mesh, "visual", None), "uv", None)
    if uv is None:
        return 0.0
    arr = np.asarray(uv)
    if arr.ndim != 2 or len(arr) == 0:
        return 0.0
    finite = np.all(np.isfinite(arr), axis=1)
    return float(np.count_nonzero(finite) / len(arr))


def inspect_mesh(path: str | Path) -> MeshQAReport:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    scene = _scene_from_file(path)
    meshes = [g for g in scene.geometry.values() if isinstance(g, trimesh.Trimesh)]
    if not meshes:
        raise ValueError("No triangle mesh geometry found")

    face_count = sum(len(m.faces) for m in meshes)
    vertex_count = sum(len(m.vertices) for m in meshes)
    degenerate = sum(_degenerate_count(m) for m in meshes)
    area = float(sum(float(m.area) for m in meshes))
    watertight = all(bool(m.is_watertight) for m in meshes)
    winding = all(bool(m.is_winding_consistent) for m in meshes)
    bodies = sum(max(1, int(m.body_count)) for m in meshes)
    uv_weighted = sum(_uv_ratio(m) * max(len(m.vertices), 1) for m in meshes) / max(vertex_count, 1)

    bounds = np.vstack([m.bounds for m in meshes])
    bmin = np.min(bounds, axis=0)
    bmax = np.max(bounds, axis=0)
    ext = bmax - bmin
    warnings: list[str] = []
    ratio = degenerate / max(face_count, 1)
    if ratio >= 0.01:
        warnings.append("Degenerate-face ratio is >=1%; repair before sculpt subdivision or baking.")
    if not winding:
        warnings.append("Inconsistent winding detected; normals/topology repair is required.")
    if not watertight:
        warnings.append("Mesh is not watertight. This may be acceptable for characters but must be deliberate for printing/displacement workflows.")
    if uv_weighted == 0:
        warnings.append("No UV coordinates detected; texturing/UDIM bake requires unwrap first.")

    return MeshQAReport(
        path=str(path),
        format=path.suffix.lower().lstrip("."),
        face_count=face_count,
        vertex_count=vertex_count,
        geometry_count=len(meshes),
        body_count=bodies,
        watertight=watertight,
        winding_consistent=winding,
        degenerate_face_count=degenerate,
        degenerate_face_ratio=float(ratio),
        uv_vertex_ratio=float(uv_weighted),
        surface_area=area,
        bounds_min=tuple(float(x) for x in bmin),
        bounds_max=tuple(float(x) for x in bmax),
        extents=tuple(float(x) for x in ext),
        warnings=warnings,
    )
