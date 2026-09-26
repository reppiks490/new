from __future__ import annotations

from pydantic import BaseModel, Field

from app.providers.models import ProviderId
from app.providers.scoring import CandidateMetrics, CandidateScore, score_candidate
from app.qa.mesh import MeshQAReport
from app.qa.textures import TextureQAReport


class PromotionDecision(BaseModel):
    provider: ProviderId
    accepted: bool
    score: CandidateScore
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def build_metrics(provider: ProviderId, mesh: MeshQAReport, textures: list[TextureQAReport], *, pbr_channel_count: int, source_similarity: float | None = None, rig_ready: bool = False, portrait_specialist: bool = False) -> CandidateMetrics:
    max_tex = max((t.max_dimension for t in textures), default=None)
    return CandidateMetrics(
        provider=provider,
        face_count=mesh.face_count,
        manifold_ratio=1.0 if mesh.watertight else 0.75,
        degenerate_face_ratio=mesh.degenerate_face_ratio,
        uv_coverage_ratio=mesh.uv_vertex_ratio,
        pbr_channel_count=pbr_channel_count,
        max_texture_resolution=max_tex,
        rig_ready=rig_ready,
        portrait_specialist=portrait_specialist,
        source_similarity=source_similarity,
        notes=mesh.warnings + [w for t in textures for w in t.warnings],
    )


def decide_promotion(provider: ProviderId, mesh: MeshQAReport, textures: list[TextureQAReport], *, target_faces: int, pbr_channel_count: int, source_similarity: float | None = None, rig_ready: bool = False, portrait_priority: bool = False, portrait_specialist: bool = False) -> PromotionDecision:
    metrics = build_metrics(provider, mesh, textures, pbr_channel_count=pbr_channel_count, source_similarity=source_similarity, rig_ready=rig_ready, portrait_specialist=portrait_specialist)
    score = score_candidate(metrics, target_faces=target_faces, portrait_priority=portrait_priority)
    blockers: list[str] = []
    if mesh.face_count <= 0:
        blockers.append("Mesh contains no faces.")
    if mesh.degenerate_face_ratio >= 0.02:
        blockers.append("Degenerate face ratio >=2%.")
    if not mesh.winding_consistent:
        blockers.append("Mesh winding is inconsistent.")
    if mesh.uv_vertex_ratio < 0.5 and textures:
        blockers.append("Textured candidate has insufficient measured UV coverage.")
    return PromotionDecision(provider=provider, accepted=not blockers, score=score, blockers=blockers, warnings=mesh.warnings + score.warnings)
