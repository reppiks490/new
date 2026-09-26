from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from pydantic import BaseModel, Field

from app.providers.geometry import MeshInspection, candidate_metrics_from_mesh, inspect_mesh
from app.providers.models import ProviderId
from app.providers.provenance import sha256_file
from app.providers.scoring import CandidateScore, rank_candidates


class LocalCandidate(BaseModel):
    provider: ProviderId
    model_path: str
    pbr_channel_count: int = Field(default=0, ge=0)
    max_texture_resolution: int | None = None
    rig_ready: bool = False
    portrait_specialist: bool = False
    source_similarity: float | None = Field(default=None, ge=0, le=1)


class EvaluatedCandidate(BaseModel):
    candidate: LocalCandidate
    inspection: MeshInspection
    score: CandidateScore
    sha256: str


class PromotionReceipt(BaseModel):
    receipt_schema: str = "character3d-candidate-promotion-v1"
    promoted_at: float
    canonical_model_path: str
    winner: EvaluatedCandidate
    alternatives: list[EvaluatedCandidate] = Field(default_factory=list)


def evaluate_local_candidates(
    candidates: list[LocalCandidate],
    *,
    target_faces: int = 2_000_000,
    portrait_priority: bool = False,
) -> list[EvaluatedCandidate]:
    if not candidates:
        raise ValueError("At least one local candidate is required")

    inspected: list[tuple[LocalCandidate, MeshInspection]] = []
    metrics = []
    for candidate in candidates:
        inspection = inspect_mesh(candidate.model_path)
        inspected.append((candidate, inspection))
        metrics.append(
            candidate_metrics_from_mesh(
                candidate.provider,
                inspection,
                pbr_channel_count=candidate.pbr_channel_count,
                max_texture_resolution=candidate.max_texture_resolution,
                rig_ready=candidate.rig_ready,
                portrait_specialist=candidate.portrait_specialist,
                source_similarity=candidate.source_similarity,
            )
        )

    # CandidateScore only keys by provider. Multiple outputs from one provider are valid, so score
    # each candidate independently rather than joining by provider id.
    scored = [
        rank_candidates([metric], target_faces=target_faces, portrait_priority=portrait_priority)[0]
        for metric in metrics
    ]
    result = [
        EvaluatedCandidate(
            candidate=candidate,
            inspection=inspection,
            score=score,
            sha256=sha256_file(candidate.model_path),
        )
        for (candidate, inspection), score in zip(inspected, scored, strict=True)
    ]
    return sorted(result, key=lambda item: item.score.total, reverse=True)


def promote_best_candidate(
    candidates: list[LocalCandidate],
    canonical_model_path: str | Path,
    *,
    target_faces: int = 2_000_000,
    portrait_priority: bool = False,
    receipt_path: str | Path | None = None,
) -> PromotionReceipt:
    ranked = evaluate_local_candidates(candidates, target_faces=target_faces, portrait_priority=portrait_priority)
    winner = ranked[0]
    source = Path(winner.candidate.model_path)
    target = Path(canonical_model_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    tmp.unlink(missing_ok=True)
    shutil.copy2(source, tmp)
    if sha256_file(tmp) != winner.sha256:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("Canonical promotion copy failed SHA-256 verification")
    tmp.replace(target)

    receipt = PromotionReceipt(
        promoted_at=time.time(),
        canonical_model_path=str(target),
        winner=winner,
        alternatives=ranked[1:],
    )
    if receipt_path is not None:
        rp = Path(receipt_path)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(json.dumps(receipt.model_dump(mode="json"), indent=2, sort_keys=True), encoding="utf-8")
    return receipt
