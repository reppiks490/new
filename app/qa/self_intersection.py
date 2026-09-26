from __future__ import annotations
from pathlib import Path
import numpy as np
import trimesh
from pydantic import BaseModel, Field

class IntersectionQAReport(BaseModel):
    path: str
    face_count: int
    suspicious_face_count: int
    suspicious_ratio: float = Field(ge=0, le=1)
    suspicious_faces: list[int] = Field(default_factory=list)
    method: str
    warnings: list[str] = Field(default_factory=list)


def localize_self_intersection_candidates(path: str | Path, *, max_report: int=500) -> IntersectionQAReport:
    """Broad-phase candidate localization via triangle AABB overlap.

    This deliberately does not claim exact triangle/triangle intersection. It provides bounded regions
    for Blender/exact kernels to inspect next, avoiding false precision in the lightweight QA process.
    """
    path=Path(path); mesh=trimesh.load(path, force='mesh', process=False)
    if not isinstance(mesh,trimesh.Trimesh): raise ValueError('single triangle mesh required')
    tri=np.asarray(mesh.triangles); n=len(tri)
    if n==0: return IntersectionQAReport(path=str(path),face_count=0,suspicious_face_count=0,suspicious_ratio=0,method='aabb_broadphase')
    mins=tri.min(axis=1); maxs=tri.max(axis=1); suspicious=set()
    # Chunked vectorization keeps memory bounded; adjacency is excluded because neighboring faces naturally overlap at edges.
    adjacency={tuple(sorted(x)) for x in np.asarray(mesh.face_adjacency,dtype=int)}
    chunk=512
    for start in range(0,n,chunk):
        stop=min(n,start+chunk)
        overlap=(mins[start:stop,None,:] <= maxs[None,:,:]).all(axis=2) & (maxs[start:stop,None,:] >= mins[None,:,:]).all(axis=2)
        rows,cols=np.nonzero(overlap)
        for r,c in zip(rows.tolist(),cols.tolist()):
            a=start+r
            if c<=a or (a,c) in adjacency: continue
            suspicious.add(a); suspicious.add(c)
            if len(suspicious)>=max_report: break
        if len(suspicious)>=max_report: break
    ids=sorted(suspicious)[:max_report]; ratio=len(ids)/n
    warnings=[]
    if ids: warnings.append('Broad-phase overlap candidates found; run exact intersection/repair in Blender or a robust geometry kernel before displacement/printing.')
    return IntersectionQAReport(path=str(path),face_count=n,suspicious_face_count=len(ids),suspicious_ratio=ratio,suspicious_faces=ids,method='aabb_broadphase_nonadjacent',warnings=warnings)
