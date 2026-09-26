from __future__ import annotations
from typing import Iterable
import math
import numpy as np
from pydantic import BaseModel, Field

class IdentityRegion(BaseModel):
    name: str
    indices: list[int]
    weight: float = Field(gt=0)

class RegionScore(BaseModel):
    name: str
    weight: float
    point_count: int
    rms_error: float
    max_error: float
    similarity: float

class WeightedIdentityReport(BaseModel):
    weighted_similarity: float = Field(ge=0, le=1)
    global_rms_error: float = Field(ge=0)
    regions: list[RegionScore]
    warnings: list[str] = Field(default_factory=list)


def _normalize_and_align(ref: np.ndarray, cand: np.ndarray) -> tuple[np.ndarray,np.ndarray]:
    ref = ref-ref.mean(0,keepdims=True); cand=cand-cand.mean(0,keepdims=True)
    sr=float(np.sqrt(np.sum(ref*ref)/len(ref))); sc=float(np.sqrt(np.sum(cand*cand)/len(cand)))
    if min(sr,sc)<=1e-12: raise ValueError('degenerate landmarks')
    ref/=sr; cand/=sc
    u,_,vt=np.linalg.svd(cand.T@ref); rot=u@vt
    if np.linalg.det(rot)<0:
        u[:,-1]*=-1; rot=u@vt
    return ref,cand@rot


def compare_landmarks_by_region(reference: Iterable[Iterable[float]], candidate: Iterable[Iterable[float]], regions: list[IdentityRegion]) -> WeightedIdentityReport:
    ref=np.asarray(list(reference),dtype=float); cand=np.asarray(list(candidate),dtype=float)
    if ref.shape!=cand.shape or ref.ndim!=2 or ref.shape[0]<3 or ref.shape[1] not in (2,3): raise ValueError('landmark arrays must match Nx2/Nx3')
    if not regions: raise ValueError('at least one identity region is required')
    refa,canda=_normalize_and_align(ref,cand)
    errors=np.linalg.norm(refa-canda,axis=1)
    seen=set(); scores=[]; total_w=0.0; weighted=0.0
    for region in regions:
        if not region.indices: raise ValueError(f'region {region.name} has no indices')
        if any(i<0 or i>=len(ref) for i in region.indices): raise ValueError(f'region {region.name} contains invalid landmark index')
        idx=np.asarray(region.indices,dtype=int); seen.update(region.indices)
        vals=errors[idx]; rms=float(np.sqrt(np.mean(vals**2))); maximum=float(vals.max()); sim=float(math.exp(-3*rms))
        scores.append(RegionScore(name=region.name,weight=region.weight,point_count=len(idx),rms_error=round(rms,8),max_error=round(maximum,8),similarity=round(sim,8)))
        total_w+=region.weight; weighted+=region.weight*sim
    warnings=[]
    result=weighted/total_w
    critical=[s for s in scores if s.weight>=2 and s.similarity<0.90]
    if critical: warnings.append('One or more high-weight identity regions fell below 0.90 similarity.')
    if len(seen)<len(ref): warnings.append('Some landmarks are not assigned to any weighted identity region.')
    return WeightedIdentityReport(weighted_similarity=round(result,8),global_rms_error=round(float(np.sqrt(np.mean(errors**2))),8),regions=scores,warnings=warnings)
