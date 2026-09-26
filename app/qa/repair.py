from __future__ import annotations

from pathlib import Path
import shutil

import trimesh
from pydantic import BaseModel, Field

from app.providers.provenance import sha256_file
from app.qa.mesh import MeshQAReport, inspect_mesh
from app.qa.self_intersection import IntersectionQAReport, localize_self_intersection_candidates


class RepairAction(BaseModel):
    action: str
    reason: str
    risk: str
    enabled_by_default: bool


class MeshRepairPlan(BaseModel):
    source_path: str
    preflight: MeshQAReport
    intersections: IntersectionQAReport
    actions: list[RepairAction]
    safe_automatic: bool
    warnings: list[str] = Field(default_factory=list)


class MeshRepairReceipt(BaseModel):
    source_path: str
    output_path: str
    source_sha256: str
    output_sha256: str
    applied_actions: list[str]
    before: MeshQAReport
    after: MeshQAReport
    warnings: list[str] = Field(default_factory=list)


def compile_repair_plan(path: str | Path) -> MeshRepairPlan:
    report = inspect_mesh(path)
    intersections = localize_self_intersection_candidates(path)
    actions: list[RepairAction] = []
    if report.degenerate_face_count:
        actions.append(RepairAction(action="remove_degenerate_faces", reason="Degenerate triangles can destabilize subdivision, baking and export.", risk="low", enabled_by_default=True))
    if not report.winding_consistent:
        actions.append(RepairAction(action="fix_normals_and_winding", reason="Face orientation is inconsistent.", risk="low", enabled_by_default=True))
    actions.append(RepairAction(action="remove_unreferenced_vertices", reason="Discard orphan vertices after topology cleanup.", risk="low", enabled_by_default=True))
    if not report.watertight:
        actions.append(RepairAction(action="fill_small_holes", reason="May be needed for print/volumetric workflows but can change intended openings.", risk="medium", enabled_by_default=False))
    if intersections.suspicious_face_count:
        actions.append(RepairAction(action="exact_intersection_repair", reason="Broad-phase overlap candidates require a robust exact kernel or Blender inspection.", risk="high", enabled_by_default=False))
    warnings: list[str] = []
    safe = not intersections.suspicious_face_count
    if intersections.suspicious_face_count:
        warnings.append("Automatic exact self-intersection repair is intentionally not attempted in the lightweight local path.")
    return MeshRepairPlan(source_path=str(path), preflight=report, intersections=intersections, actions=actions, safe_automatic=safe, warnings=warnings)


def apply_conservative_repairs(path: str | Path, output_path: str | Path, *, fill_small_holes: bool = False) -> MeshRepairReceipt:
    source = Path(path)
    target = Path(output_path)
    before = inspect_mesh(source)
    loaded = trimesh.load(source, force="mesh", process=False)
    if not isinstance(loaded, trimesh.Trimesh):
        raise ValueError("conservative repair requires a single triangle mesh")
    mesh = loaded.copy()
    applied: list[str] = []

    try:
        mask = mesh.nondegenerate_faces()
        if len(mask) and not bool(mask.all()):
            mesh.update_faces(mask)
            applied.append("remove_degenerate_faces")
    except Exception:
        pass

    before_vertices = len(mesh.vertices)
    mesh.remove_unreferenced_vertices()
    if len(mesh.vertices) != before_vertices:
        applied.append("remove_unreferenced_vertices")

    if not mesh.is_winding_consistent:
        mesh.fix_normals(multibody=True)
        applied.append("fix_normals_and_winding")

    if fill_small_holes and not mesh.is_watertight:
        if bool(mesh.fill_holes()):
            applied.append("fill_small_holes")

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    tmp.unlink(missing_ok=True)
    mesh.export(tmp, file_type=target.suffix.lower().lstrip("."))
    tmp.replace(target)
    after = inspect_mesh(target)
    warnings: list[str] = []
    if after.degenerate_face_ratio > before.degenerate_face_ratio + 1e-12:
        warnings.append("Degenerate-face ratio increased; reject this repaired candidate.")
    if before.winding_consistent and not after.winding_consistent:
        warnings.append("Winding regressed; reject this repaired candidate.")
    return MeshRepairReceipt(
        source_path=str(source),
        output_path=str(target),
        source_sha256=sha256_file(source),
        output_sha256=sha256_file(target),
        applied_actions=applied,
        before=before,
        after=after,
        warnings=warnings,
    )
