from __future__ import annotations

from pydantic import BaseModel, Field

from app.qa.exact_intersections import ExactIntersectionReport
from app.qa.identity_regions import WeightedIdentityReport
from app.qa.mesh import MeshQAReport


class RepairAcceptancePolicy(BaseModel):
    min_weighted_identity: float = Field(default=0.97, ge=0, le=1)
    max_identity_rms: float = Field(default=0.08, ge=0)
    require_intersection_reduction: bool = True
    max_degenerate_ratio: float = Field(default=0.01, ge=0, le=1)
    require_consistent_winding: bool = True


class RepairAcceptanceReport(BaseModel):
    accepted: bool
    intersection_pairs_before: int
    intersection_pairs_after: int
    intersection_reduction: int
    weighted_identity: float
    global_identity_rms: float
    degenerate_ratio_before: float
    degenerate_ratio_after: float
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def evaluate_repair_acceptance(
    before_intersections: ExactIntersectionReport,
    after_intersections: ExactIntersectionReport,
    before_mesh: MeshQAReport,
    after_mesh: MeshQAReport,
    identity: WeightedIdentityReport,
    policy: RepairAcceptancePolicy | None = None,
) -> RepairAcceptanceReport:
    policy = policy or RepairAcceptancePolicy()
    blockers: list[str] = []
    warnings: list[str] = []
    reduction = before_intersections.intersecting_pair_count - after_intersections.intersecting_pair_count

    if policy.require_intersection_reduction and before_intersections.intersecting_pair_count > 0 and reduction <= 0:
        blockers.append("Repair did not reduce exact intersection pair count.")
    if after_intersections.intersecting_pair_count > 0:
        warnings.append(f"{after_intersections.intersecting_pair_count} exact intersection pairs remain after repair.")
    if identity.weighted_similarity < policy.min_weighted_identity:
        blockers.append(
            f"Weighted identity similarity {identity.weighted_similarity:.5f} is below {policy.min_weighted_identity:.5f}."
        )
    if identity.global_rms_error > policy.max_identity_rms:
        blockers.append(
            f"Identity RMS {identity.global_rms_error:.5f} exceeds {policy.max_identity_rms:.5f}."
        )
    if after_mesh.degenerate_face_ratio > policy.max_degenerate_ratio:
        blockers.append(
            f"Degenerate-face ratio {after_mesh.degenerate_face_ratio:.5%} exceeds {policy.max_degenerate_ratio:.5%}."
        )
    if after_mesh.degenerate_face_ratio > before_mesh.degenerate_face_ratio + 1e-12:
        warnings.append("Repair increased the degenerate-face ratio.")
    if before_mesh.watertight and not after_mesh.watertight:
        blockers.append("Repair opened a previously closed surface (holes left unfilled).")
    if policy.require_consistent_winding and not after_mesh.winding_consistent:
        blockers.append("Repaired mesh has inconsistent winding.")

    return RepairAcceptanceReport(
        accepted=not blockers,
        intersection_pairs_before=before_intersections.intersecting_pair_count,
        intersection_pairs_after=after_intersections.intersecting_pair_count,
        intersection_reduction=reduction,
        weighted_identity=identity.weighted_similarity,
        global_identity_rms=identity.global_rms_error,
        degenerate_ratio_before=before_mesh.degenerate_face_ratio,
        degenerate_ratio_after=after_mesh.degenerate_face_ratio,
        blockers=blockers,
        warnings=warnings,
    )
