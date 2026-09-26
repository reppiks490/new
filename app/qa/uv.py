from __future__ import annotations

from pathlib import Path
import numpy as np
import trimesh
from pydantic import BaseModel, Field

class UVQAReport(BaseModel):
    path: str
    face_count: int
    uv_vertex_count: int
    finite_ratio: float = Field(ge=0, le=1)
    uv_bounds_min: tuple[float,float]
    uv_bounds_max: tuple[float,float]
    tile_count: int
    occupancy_estimate: float = Field(ge=0, le=1)
    texel_density_cv: float = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)


def _tri_area2d(p: np.ndarray) -> np.ndarray:
    return np.abs((p[:,1,0]-p[:,0,0])*(p[:,2,1]-p[:,0,1]) - (p[:,2,0]-p[:,0,0])*(p[:,1,1]-p[:,0,1])) * 0.5


def inspect_uv(path: str | Path, grid: int = 256) -> UVQAReport:
    path = Path(path)
    loaded = trimesh.load(path, force='mesh', process=False)
    if not isinstance(loaded, trimesh.Trimesh):
        raise ValueError('UV QA currently requires a single triangle mesh')
    uv = getattr(getattr(loaded, 'visual', None), 'uv', None)
    if uv is None:
        raise ValueError('Mesh has no UV coordinates')
    uv = np.asarray(uv, dtype=float)
    finite = np.all(np.isfinite(uv), axis=1)
    clean = uv[finite]
    if clean.size == 0:
        raise ValueError('UV coordinates contain no finite values')
    faces = np.asarray(loaded.faces, dtype=int)
    tri_uv = uv[faces]
    tri_uv_area = _tri_area2d(tri_uv)
    tri_3d_area = np.asarray(loaded.area_faces, dtype=float)
    valid = (tri_3d_area > 1e-15) & np.isfinite(tri_uv_area) & (tri_uv_area > 1e-15)
    density = np.sqrt(tri_uv_area[valid] / tri_3d_area[valid]) if np.any(valid) else np.array([])
    cv = float(np.std(density) / max(np.mean(density), 1e-15)) if density.size else 0.0

    tiles = set()
    bitmap = np.zeros((grid, grid), dtype=bool)
    # Conservative raster-free occupancy estimate: mark bounding grid cells of each UV triangle in its tile.
    for tri in tri_uv:
        if not np.all(np.isfinite(tri)):
            continue
        centroid = tri.mean(axis=0)
        tile = (int(np.floor(centroid[0])), int(np.floor(centroid[1])))
        tiles.add(tile)
        local = tri - np.floor(centroid)
        lo = np.clip(np.floor(local.min(axis=0)*grid).astype(int), 0, grid-1)
        hi = np.clip(np.ceil(local.max(axis=0)*grid).astype(int), 0, grid-1)
        if tile == (0,0):
            bitmap[lo[1]:hi[1]+1, lo[0]:hi[0]+1] = True
    occupancy = float(bitmap.mean())
    warnings=[]
    if cv > 0.75:
        warnings.append('High texel-density variation detected; normalize important character regions before hero baking.')
    if occupancy < 0.35 and (0,0) in tiles:
        warnings.append('Primary UV tile occupancy is low; texture memory may be underutilized.')
    return UVQAReport(
        path=str(path), face_count=len(faces), uv_vertex_count=len(uv),
        finite_ratio=float(np.count_nonzero(finite)/max(len(finite),1)),
        uv_bounds_min=tuple(float(x) for x in clean.min(axis=0)),
        uv_bounds_max=tuple(float(x) for x in clean.max(axis=0)), tile_count=len(tiles),
        occupancy_estimate=occupancy, texel_density_cv=cv, warnings=warnings)
