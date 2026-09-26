from __future__ import annotations

from pathlib import Path

import numpy as np
from pydantic import BaseModel, Field

from app.providers.models import ProviderId
from app.providers.scoring import CandidateMetrics


class MeshInspection(BaseModel):
    path: str
    vertices: int = 0
    faces: int = 0
    components: int = 0
    watertight: bool = False
    winding_consistent: bool = False
    manifold_edge_ratio: float = Field(ge=0.0, le=1.0)
    degenerate_face_ratio: float = Field(ge=0.0, le=1.0)
    uv_present: bool = False
    bounding_box_diagonal: float = 0.0
    surface_area: float = 0.0
    volume: float | None = None
    warnings: list[str] = Field(default_factory=list)


def inspect_mesh(path: str | Path) -> MeshInspection:
    try:
        import trimesh
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("trimesh is required for local mesh inspection") from exc

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)

    loaded = trimesh.load(path, process=False, force="scene")
    geometries = [g for g in loaded.geometry.values() if isinstance(g, trimesh.Trimesh)]
    if not geometries:
        raise ValueError(f"No mesh geometry found in {path}")
    mesh = trimesh.util.concatenate(tuple(geometries)) if len(geometries) > 1 else geometries[0]

    faces = np.asarray(mesh.faces, dtype=np.int64)
    face_count = int(len(faces))
    vertex_count = int(len(mesh.vertices))
    warnings: list[str] = []

    if face_count:
        e01 = faces[:, [0, 1]]
        e12 = faces[:, [1, 2]]
        e20 = faces[:, [2, 0]]
        edges = np.sort(np.vstack((e01, e12, e20)), axis=1)
        _, edge_counts = np.unique(edges, axis=0, return_counts=True)
        manifold_ratio = float(np.mean(edge_counts == 2)) if len(edge_counts) else 0.0

        bounds = np.asarray(mesh.bounds, dtype=float)
        diagonal = float(np.linalg.norm(bounds[1] - bounds[0])) if bounds.shape == (2, 3) else 0.0
        scale_area = max(diagonal * diagonal, 1.0)
        areas = np.asarray(mesh.area_faces, dtype=float)
        degenerate_ratio = float(np.mean(areas <= scale_area * 1e-14)) if len(areas) else 0.0
    else:
        manifold_ratio = 0.0
        degenerate_ratio = 1.0
        diagonal = 0.0

    uv = getattr(mesh.visual, "uv", None)
    uv_present = uv is not None and len(uv) == vertex_count
    if not uv_present:
        warnings.append("No complete vertex UV set detected.")
    if manifold_ratio < 0.98:
        warnings.append("Mesh has a material fraction of boundary/non-manifold edges.")
    if degenerate_ratio > 0.001:
        warnings.append("Mesh contains a material fraction of degenerate triangles.")

    components = len(mesh.split(only_watertight=False)) if face_count else 0
    volume = float(mesh.volume) if bool(mesh.is_watertight) else None
    return MeshInspection(
        path=str(path),
        vertices=vertex_count,
        faces=face_count,
        components=components,
        watertight=bool(mesh.is_watertight),
        winding_consistent=bool(mesh.is_winding_consistent),
        manifold_edge_ratio=round(manifold_ratio, 8),
        degenerate_face_ratio=round(degenerate_ratio, 8),
        uv_present=bool(uv_present),
        bounding_box_diagonal=diagonal,
        surface_area=float(mesh.area),
        volume=volume,
        warnings=warnings,
    )


def candidate_metrics_from_mesh(
    provider: ProviderId,
    inspection: MeshInspection,
    *,
    pbr_channel_count: int = 0,
    max_texture_resolution: int | None = None,
    rig_ready: bool = False,
    portrait_specialist: bool = False,
    source_similarity: float | None = None,
) -> CandidateMetrics:
    return CandidateMetrics(
        provider=provider,
        face_count=inspection.faces,
        manifold_ratio=inspection.manifold_edge_ratio,
        degenerate_face_ratio=inspection.degenerate_face_ratio,
        uv_coverage_ratio=1.0 if inspection.uv_present else 0.0,
        pbr_channel_count=pbr_channel_count,
        max_texture_resolution=max_texture_resolution,
        rig_ready=rig_ready,
        portrait_specialist=portrait_specialist,
        source_similarity=source_similarity,
        notes=list(inspection.warnings),
    )
