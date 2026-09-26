from __future__ import annotations

from pathlib import Path
import numpy as np
from PIL import Image
from pydantic import BaseModel, Field


class ViewSimilarity(BaseModel):
    reference: str
    candidate: str
    structure_similarity: float = Field(ge=0, le=1)
    edge_similarity: float = Field(ge=0, le=1)
    combined_similarity: float = Field(ge=0, le=1)


class MultiViewSimilarityReport(BaseModel):
    views: list[ViewSimilarity]
    mean_similarity: float = Field(ge=0, le=1)
    worst_similarity: float = Field(ge=0, le=1)
    warnings: list[str] = Field(default_factory=list)


def _gray(path: str | Path, size: tuple[int,int]=(256,256)) -> np.ndarray:
    with Image.open(path) as im:
        arr=np.asarray(im.convert("L").resize(size, Image.Resampling.BILINEAR), dtype=np.float64)/255.0
    return arr


def _normalized_structure(a: np.ndarray, b: np.ndarray) -> float:
    aa=(a-a.mean())/(a.std()+1e-8); bb=(b-b.mean())/(b.std()+1e-8)
    corr=float(np.mean(aa*bb))
    return max(0.0,min(1.0,(corr+1.0)/2.0))


def _edges(x: np.ndarray) -> np.ndarray:
    gx=np.diff(x,axis=1,append=x[:,-1:]); gy=np.diff(x,axis=0,append=x[-1:,:])
    return np.sqrt(gx*gx+gy*gy)


def compare_rendered_view(reference: str | Path, candidate: str | Path) -> ViewSimilarity:
    a=_gray(reference); b=_gray(candidate)
    structure=_normalized_structure(a,b)
    ea=_edges(a); eb=_edges(b)
    denom=float(np.mean(np.abs(ea))+np.mean(np.abs(eb))+1e-8)
    edge=max(0.0,min(1.0,1.0-float(np.mean(np.abs(ea-eb)))/denom))
    combined=0.7*structure+0.3*edge
    return ViewSimilarity(reference=str(reference),candidate=str(candidate),structure_similarity=round(structure,8),edge_similarity=round(edge,8),combined_similarity=round(combined,8))


def compare_multiview(reference_paths: list[str | Path], candidate_paths: list[str | Path]) -> MultiViewSimilarityReport:
    if len(reference_paths) != len(candidate_paths) or not reference_paths:
        raise ValueError("reference and candidate view lists must be non-empty and have equal length")
    views=[compare_rendered_view(a,b) for a,b in zip(reference_paths,candidate_paths,strict=True)]
    mean=float(np.mean([v.combined_similarity for v in views])); worst=min(v.combined_similarity for v in views)
    warnings=[]
    if worst < 0.70: warnings.append("At least one rendered view is materially inconsistent with its reference.")
    return MultiViewSimilarityReport(views=views,mean_similarity=round(mean,8),worst_similarity=round(worst,8),warnings=warnings)
