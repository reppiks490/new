from __future__ import annotations

from pydantic import BaseModel, Field

from app.providers.models import ProviderId


class CandidateMetrics(BaseModel):
    provider: ProviderId
    face_count: int | None = None
    manifold_ratio: float | None = Field(default=None, ge=0, le=1)
    degenerate_face_ratio: float | None = Field(default=None, ge=0, le=1)
    uv_coverage_ratio: float | None = Field(default=None, ge=0, le=1)
    pbr_channel_count: int = Field(default=0, ge=0)
    max_texture_resolution: int | None = None
    rig_ready: bool = False
    portrait_specialist: bool = False
    source_similarity: float | None = Field(default=None, ge=0, le=1)
    notes: list[str] = Field(default_factory=list)


class CandidateScore(BaseModel):
    provider: ProviderId
    total: float
    components: dict[str, float]
    warnings: list[str] = Field(default_factory=list)


def score_candidate(metrics: CandidateMetrics, *, target_faces: int = 2_000_000, portrait_priority: bool = False) -> CandidateScore:
    c: dict[str, float] = {}
    warnings: list[str] = []
    if metrics.face_count:
        ratio = min(metrics.face_count / max(target_faces, 1), 1.0)
        c["density"] = 22.0 * ratio
        if metrics.face_count > target_faces * 2:
            warnings.append("Density greatly exceeds target; downstream retopo/baking is mandatory.")
    else:
        c["density"] = 0.0
        warnings.append("Face count not measured yet.")

    c["manifold"] = 18.0 * (metrics.manifold_ratio if metrics.manifold_ratio is not None else 0.0)
    c["degenerate_cleanliness"] = 12.0 * (1.0 - (metrics.degenerate_face_ratio if metrics.degenerate_face_ratio is not None else 1.0))
    c["uv"] = 10.0 * (metrics.uv_coverage_ratio if metrics.uv_coverage_ratio is not None else 0.0)
    c["pbr"] = min(metrics.pbr_channel_count, 4) / 4.0 * 10.0
    if metrics.max_texture_resolution:
        c["texture_resolution"] = 10.0 * min(metrics.max_texture_resolution / 8192.0, 1.0)
    else:
        c["texture_resolution"] = 0.0
    c["rig_readiness"] = 8.0 if metrics.rig_ready else 0.0
    c["source_similarity"] = 8.0 * (metrics.source_similarity if metrics.source_similarity is not None else 0.0)
    c["portrait_specialization"] = 2.0 if portrait_priority and metrics.portrait_specialist else 0.0
    return CandidateScore(provider=metrics.provider, total=round(sum(c.values()), 4), components={k: round(v, 4) for k, v in c.items()}, warnings=warnings)


def rank_candidates(candidates: list[CandidateMetrics], *, target_faces: int = 2_000_000, portrait_priority: bool = False) -> list[CandidateScore]:
    scores = [score_candidate(c, target_faces=target_faces, portrait_priority=portrait_priority) for c in candidates]
    return sorted(scores, key=lambda x: x.total, reverse=True)
