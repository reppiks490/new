from __future__ import annotations
import math
from pydantic import BaseModel, Field
from app.core.scene_models import SceneSpec

class PlacementReport(BaseModel):
    instance_count: int
    overlapping_pairs: list[tuple[str, str]] = Field(default_factory=list)
    out_of_bounds: list[str] = Field(default_factory=list)
    passed: bool
    warnings: list[str] = Field(default_factory=list)

def qa_scene_placement(scene: SceneSpec) -> PlacementReport:
    hx, hy, hz = (b / 2 for b in scene.bounds_meters)
    out_of_bounds = []
    for a in scene.assets:
        x, y, z = a.transform.position
        if abs(x) > hx or abs(y) > hy or abs(z) > hz:
            out_of_bounds.append(a.instance_id)

    radii = {a.instance_id: a.bounding_radius_m for a in scene.assets if a.bounding_radius_m}
    positions = {a.instance_id: a.transform.position for a in scene.assets}
    ids = list(radii)
    overlaps: list[tuple[str, str]] = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            ai, aj = ids[i], ids[j]
            dist = math.dist(positions[ai], positions[aj])
            if dist < (radii[ai] + radii[aj]):
                overlaps.append((ai, aj))

    warnings = []
    if overlaps:
        warnings.append(f"{len(overlaps)} instance pair(s) have overlapping bounding spheres.")
    if out_of_bounds:
        warnings.append(f"{len(out_of_bounds)} instance(s) fall outside declared scene bounds: {out_of_bounds}")

    return PlacementReport(
        instance_count=len(scene.assets),
        overlapping_pairs=overlaps,
        out_of_bounds=out_of_bounds,
        # Overlap can be intentional (attached props, stacked geometry) so it's a
        # warning; being outside the declared scene bounds is a real placement
        # error and fails QA.
        passed=not out_of_bounds,
        warnings=warnings,
    )
