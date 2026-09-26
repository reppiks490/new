from __future__ import annotations

"""Source polygon-topology analysis (triangles vs. quads vs. n-gons).

Scope note: this only applies to formats that actually preserve polygon
structure in their source face definitions -- OBJ is the practical case
here. GLB/glTF has NO native quad primitive mode (confirmed against the
Khronos glTF 2.0 spec: primitive modes are POINTS/LINES/LINE_LOOP/
LINE_STRIP/TRIANGLES/TRIANGLE_STRIP/TRIANGLE_FAN -- no quad mode exists),
so any quad/n-gon geometry is necessarily already triangulated by the time
it's in a GLB, and there is nothing left to analyze. trimesh itself also
triangulates on load regardless of source format, which is why this reads
raw `f` face lines directly rather than going through trimesh at all --
trimesh's own Trimesh class has already lost the original polygon
structure by the time you have one.
"""

from pathlib import Path

from pydantic import BaseModel, Field


class TopologyReport(BaseModel):
    path: str
    triangle_count: int
    quad_count: int
    ngon_count: int  # faces with 5+ vertices
    total_faces: int
    # Exact fan-triangulation cost (sum of vertex_count-2 over every face):
    # this is what the mesh actually costs to render/rasterize, not the raw
    # source face count. A single 8-vertex n-gon is 1 "face" but 6 triangles
    # -- reporting only total_faces would silently understate real cost, the
    # exact thing the goal spec's polygon/triangle system section warns
    # against ("Do NOT advertise only raw vertex count").
    effective_triangle_count: int
    quad_ratio: float = Field(ge=0, le=1)
    triangle_ratio: float = Field(ge=0, le=1)
    ngon_ratio: float = Field(ge=0, le=1)
    warnings: list[str] = Field(default_factory=list)

    @property
    def quad_dominant(self) -> bool:
        # A quad-dominant mesh is generally friendlier for subdivision
        # surfaces / nondestructive multires (docs/ARCHITECTURE.md section 2),
        # so this is worth surfacing as a simple boolean rather than making
        # every caller re-derive it from the ratios.
        return self.quad_ratio >= 0.5


def analyze_obj_topology(path: str | Path) -> TopologyReport:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)

    tri = quad = ngon = 0
    effective_tris = 0
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("f "):
                continue
            # Face line: "f v1[/vt1][/vn1] v2... v3 ..." -- count space-
            # separated vertex references, ignoring the leading "f" token.
            tokens = line.split()[1:]
            n = len(tokens)
            if n == 3:
                tri += 1
            elif n == 4:
                quad += 1
            elif n >= 5:
                ngon += 1
            else:
                # n < 3 is a malformed face line; silently skip rather than
                # crash, consistent with this module being a QA/reporting
                # tool, not a strict validator that should abort on one
                # bad line. It contributes nothing to effective_tris either.
                continue
            # Exact fan-triangulation formula for a convex/simple polygon
            # with n vertices: n-2 triangles. n=3 -> 1, n=4 -> 2, n=5 -> 3, ...
            effective_tris += n - 2

    total = tri + quad + ngon
    warnings: list[str] = []
    if total == 0:
        warnings.append("No face lines found; file may not be a polygon mesh OBJ.")

    return TopologyReport(
        path=str(path),
        triangle_count=tri,
        quad_count=quad,
        ngon_count=ngon,
        total_faces=total,
        effective_triangle_count=effective_tris,
        quad_ratio=round(quad / total, 6) if total else 0.0,
        triangle_ratio=round(tri / total, 6) if total else 0.0,
        ngon_ratio=round(ngon / total, 6) if total else 0.0,
        warnings=warnings,
    )
