from __future__ import annotations

import math
from typing import Iterable

import numpy as np
from pydantic import BaseModel, Field


class IdentityPreservationReport(BaseModel):
    point_count: int
    dimensions: int
    normalized_rms_error: float = Field(ge=0)
    max_normalized_error: float = Field(ge=0)
    similarity: float = Field(ge=0, le=1)
    reflection_used: bool = False
    warnings: list[str] = Field(default_factory=list)


def _as_points(points: Iterable[Iterable[float]]) -> np.ndarray:
    arr = np.asarray(list(points), dtype=np.float64)
    if arr.ndim != 2 or arr.shape[0] < 3 or arr.shape[1] not in (2, 3):
        raise ValueError("landmarks must be an Nx2 or Nx3 array with at least 3 points")
    if not np.isfinite(arr).all():
        raise ValueError("landmarks must contain only finite coordinates")
    return arr


def _normalize(points: np.ndarray) -> tuple[np.ndarray, float]:
    centered = points - points.mean(axis=0, keepdims=True)
    scale = float(np.sqrt(np.sum(centered * centered) / len(points)))
    if scale <= 1e-12:
        raise ValueError("landmark configuration is degenerate")
    return centered / scale, scale


def compare_landmarks(reference: Iterable[Iterable[float]], candidate: Iterable[Iterable[float]]) -> IdentityPreservationReport:
    """Compare landmark shape after removing translation, uniform scale and rotation.

    Reflection is deliberately disallowed: mirrored identity geometry should not receive a perfect score.
    The resulting score is a preservation metric, not biometric identification.
    """
    ref = _as_points(reference)
    cand = _as_points(candidate)
    if ref.shape != cand.shape:
        raise ValueError("reference and candidate landmark arrays must have identical shape")

    ref_n, _ = _normalize(ref)
    cand_n, _ = _normalize(cand)
    cov = cand_n.T @ ref_n
    u, _, vt = np.linalg.svd(cov)
    rot = u @ vt
    reflection_used = bool(np.linalg.det(rot) < 0)
    if reflection_used:
        u[:, -1] *= -1
        rot = u @ vt
    aligned = cand_n @ rot
    per_point = np.linalg.norm(aligned - ref_n, axis=1)
    rms = float(np.sqrt(np.mean(per_point ** 2)))
    maximum = float(np.max(per_point))
    # Smoothly maps small shape errors toward 1 while strongly penalizing large deformation.
    similarity = float(math.exp(-3.0 * rms))
    warnings: list[str] = []
    if similarity < 0.85:
        warnings.append("Landmark-shape preservation fell below the hero-character target of 0.85.")
    if maximum > 0.35:
        warnings.append("At least one landmark shows a large localized normalized deviation.")
    return IdentityPreservationReport(
        point_count=len(ref),
        dimensions=ref.shape[1],
        normalized_rms_error=round(rms, 8),
        max_normalized_error=round(maximum, 8),
        similarity=round(similarity, 8),
        reflection_used=reflection_used,
        warnings=warnings,
    )
