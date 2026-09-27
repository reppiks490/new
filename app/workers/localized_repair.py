from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ConfigDict

from app.qa.exact_intersections import ExactIntersectionReport
from app.workers.blender import BlenderInvocation


class LocalizedRepairContract(BaseModel):
    source_mesh: str
    output_mesh: str
    affected_faces: list[int]
    strategy: str = "localized_patch_fill"
    boundary_rings: int = Field(default=1, ge=0, le=6)
    preserve_vertex_groups: bool = True
    preserve_shape_keys: bool = True
    # affected_faces come from app.qa.exact_intersections (trimesh triangle
    # indices). Blender's importers keep quads/ngons and may reorder faces,
    # so by default the worker re-detects in its own polygon index space;
    # "blender_polygons" means affected_faces already are Blender indices.
    face_index_space: Literal["detect_in_blender", "blender_polygons"] = "detect_in_blender"
    blockers: list[str] = Field(default_factory=list)


class LocalizedRepairReceipt(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    schema_name: str = Field(alias="schema")
    status: str
    source_mesh: str
    output_mesh: str | None = None
    affected_faces: int = 0
    created_faces: int = 0
    contract_face_count: int | None = None
    detected_faces: int | None = None
    detected_pairs: int | None = None
    remaining_intersecting_faces: int | None = None
    remaining_intersecting_pairs: int | None = None
    filled_hole_loops: int | None = None
    open_boundary_chains: int | None = None
    input_was_closed: bool | None = None
    boundary_edges_after: int | None = None
    blender_version: str | None = None
    error: str | None = None


def compile_localized_repair_contract(report: ExactIntersectionReport, source_mesh: str | Path, output_mesh: str | Path) -> LocalizedRepairContract:
    faces = sorted({p.face_a for p in report.pairs} | {p.face_b for p in report.pairs})
    blockers: list[str] = []
    if report.intersecting_pair_count == 0:
        blockers.append("No exact intersections were supplied for repair.")
    if report.truncated:
        blockers.append("Intersection report is truncated; refusing localized repair from incomplete face coverage.")
    if len(faces) > 512:
        blockers.append("Localized repair is capped at 512 directly affected faces; escalate to region remesh.")
    return LocalizedRepairContract(
        source_mesh=str(source_mesh),
        output_mesh=str(output_mesh),
        affected_faces=faces,
        blockers=blockers,
    )


def write_localized_repair_contract(contract: LocalizedRepairContract, path: str | Path) -> Path:
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(contract.model_dump(mode="json"), indent=2, sort_keys=True), encoding="utf-8")
    return p


def build_localized_repair_invocation(blender_executable: str | Path, contract_path: str | Path, worker_script: str | Path) -> BlenderInvocation:
    return BlenderInvocation(
        executable=str(blender_executable),
        args=["--background", "--disable-autoexec", "--python", str(worker_script), "--", "--contract", str(contract_path)],
    )
