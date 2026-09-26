from __future__ import annotations
from pathlib import Path
import numpy as np
import trimesh
from pydantic import BaseModel, Field

class GroomCollisionReport(BaseModel):
    strand_count: int
    sampled_point_count: int
    penetration_point_count: int
    collision_ratio: float = Field(ge=0,le=1)
    minimum_clearance: float
    passed: bool
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _ray_inside(points: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    # Brute-force +X parity test. Slow but dependency-free and deterministic for sampled QA points.
    d=np.array([1.0,0.0,0.0]); out=np.zeros(len(points),dtype=bool)
    for pi,p in enumerate(points):
        hits=[]
        for tri in triangles:
            v0,v1,v2=tri; e1=v1-v0; e2=v2-v0; h=np.cross(d,e2); det=float(np.dot(e1,h))
            if abs(det)<1e-10: continue
            inv=1.0/det; s=p-v0; u=inv*float(np.dot(s,h))
            if u<0 or u>1: continue
            q=np.cross(s,e1); v=inv*float(np.dot(d,q))
            if v<0 or u+v>1: continue
            t=inv*float(np.dot(e2,q))
            if t>1e-9: hits.append(t)
        if hits:
            hits=sorted(hits); uniq=[hits[0]]
            for x in hits[1:]:
                if abs(x-uniq[-1])>1e-7: uniq.append(x)
            out[pi]=(len(uniq)%2)==1
    return out


def qa_groom_collisions(body_mesh: str | Path, strands: list[list[list[float]]], *, sample_stride: int=2, allowed_penetration_ratio: float=0.002) -> GroomCollisionReport:
    mesh=trimesh.load(body_mesh,force='mesh',process=False)
    if not isinstance(mesh,trimesh.Trimesh): raise ValueError('body_mesh must resolve to one triangle mesh')
    pts=[]
    for strand in strands:
        arr=np.asarray(strand,dtype=float)
        if arr.ndim!=2 or arr.shape[1]!=3 or len(arr)<2: raise ValueError('each groom strand must be Nx3 with at least two points')
        pts.extend(arr[1::max(1,sample_stride)])  # roots may intentionally embed slightly in scalp
    if not pts:
        return GroomCollisionReport(strand_count=len(strands),sampled_point_count=0,penetration_point_count=0,collision_ratio=0,minimum_clearance=float('inf'),passed=True)
    points=np.asarray(pts,float)
    inside=_ray_inside(points,np.asarray(mesh.triangles)) if mesh.is_watertight else np.zeros(len(points),dtype=bool)
    try:
        _,dist,_=trimesh.proximity.closest_point_naive(mesh,points)
        min_clear=float(np.min(dist)) if len(dist) else float('inf')
    except Exception:
        min_clear=float('nan')
    count=int(inside.sum()); ratio=count/len(points); blockers=[]; warnings=[]
    if ratio>allowed_penetration_ratio: blockers.append(f'Groom penetration ratio {ratio:.4%} exceeds {allowed_penetration_ratio:.4%}.')
    elif count: warnings.append('Minor groom/body penetrations detected within configured tolerance.')
    if not mesh.is_watertight: warnings.append('Body mesh is not watertight; inside/outside collision classification was disabled and should be repeated in Blender.')
    return GroomCollisionReport(strand_count=len(strands),sampled_point_count=len(points),penetration_point_count=count,collision_ratio=ratio,minimum_clearance=min_clear,passed=not blockers,warnings=warnings,blockers=blockers)
