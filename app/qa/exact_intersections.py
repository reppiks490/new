from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import trimesh
from pydantic import BaseModel, Field

_EPS = 1e-9


class ExactIntersectionPair(BaseModel):
    face_a: int
    face_b: int
    coplanar: bool = False


class ExactIntersectionReport(BaseModel):
    path: str
    face_count: int
    tested_pairs: int
    intersecting_pair_count: int
    intersecting_face_count: int
    intersecting_ratio: float = Field(ge=0, le=1)
    pairs: list[ExactIntersectionPair] = Field(default_factory=list)
    truncated: bool = False
    method: str = "triangle_triangle_exact_cpu"
    warnings: list[str] = Field(default_factory=list)


def _point_in_tri_2d(p: np.ndarray, tri: np.ndarray) -> bool:
    a, b, c = tri
    def cross(u, v): return float(u[0] * v[1] - u[1] * v[0])
    c1 = cross(b-a, p-a); c2 = cross(c-b, p-b); c3 = cross(a-c, p-c)
    has_neg = min(c1, c2, c3) < -_EPS
    has_pos = max(c1, c2, c3) > _EPS
    return not (has_neg and has_pos)


def _seg_intersect_2d(a: np.ndarray, b: np.ndarray, c: np.ndarray, d: np.ndarray) -> bool:
    def orient(p, q, r):
        return float((q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0]))
    o1, o2, o3, o4 = orient(a,b,c), orient(a,b,d), orient(c,d,a), orient(c,d,b)
    if ((o1 > _EPS and o2 < -_EPS) or (o1 < -_EPS and o2 > _EPS)) and ((o3 > _EPS and o4 < -_EPS) or (o3 < -_EPS and o4 > _EPS)):
        return True
    def onseg(p,q,r):
        return min(p[0],r[0])-_EPS <= q[0] <= max(p[0],r[0])+_EPS and min(p[1],r[1])-_EPS <= q[1] <= max(p[1],r[1])+_EPS
    return (abs(o1)<=_EPS and onseg(a,c,b)) or (abs(o2)<=_EPS and onseg(a,d,b)) or (abs(o3)<=_EPS and onseg(c,a,d)) or (abs(o4)<=_EPS and onseg(c,b,d))


def _coplanar_tri_intersect(t1: np.ndarray, t2: np.ndarray, normal: np.ndarray) -> bool:
    axis = int(np.argmax(np.abs(normal)))
    keep = [i for i in range(3) if i != axis]
    a = t1[:, keep]; b = t2[:, keep]
    for i in range(3):
        for j in range(3):
            if _seg_intersect_2d(a[i], a[(i+1)%3], b[j], b[(j+1)%3]):
                return True
    return _point_in_tri_2d(a[0], b) or _point_in_tri_2d(b[0], a)


def _segment_triangle_intersect(p0: np.ndarray, p1: np.ndarray, tri: np.ndarray) -> bool:
    v0, v1, v2 = tri
    direction = p1 - p0
    e1 = v1 - v0; e2 = v2 - v0
    h = np.cross(direction, e2)
    det = float(np.dot(e1, h))
    if abs(det) < _EPS:
        return False
    inv = 1.0 / det
    s = p0 - v0
    u = inv * float(np.dot(s, h))
    if u < -_EPS or u > 1 + _EPS: return False
    q = np.cross(s, e1)
    v = inv * float(np.dot(direction, q))
    if v < -_EPS or u + v > 1 + _EPS: return False
    t = inv * float(np.dot(e2, q))
    return -_EPS <= t <= 1 + _EPS


def triangles_intersect(t1: Iterable[Iterable[float]], t2: Iterable[Iterable[float]]) -> tuple[bool, bool]:
    a = np.asarray(t1, dtype=float); b = np.asarray(t2, dtype=float)
    if a.shape != (3,3) or b.shape != (3,3):
        raise ValueError("triangles must be 3x3")
    n1 = np.cross(a[1]-a[0], a[2]-a[0]); n2 = np.cross(b[1]-b[0], b[2]-b[0])
    if np.linalg.norm(n1) < _EPS or np.linalg.norm(n2) < _EPS:
        return False, False
    d = np.abs((b - a[0]) @ n1)
    coplanar = bool(np.max(d) <= 1e-8 and np.linalg.norm(np.cross(n1,n2)) <= 1e-8*np.linalg.norm(n1)*np.linalg.norm(n2))
    if coplanar:
        return _coplanar_tri_intersect(a,b,n1), True
    for tri_a, tri_b in ((a,b),(b,a)):
        for i in range(3):
            if _segment_triangle_intersect(tri_a[i], tri_a[(i+1)%3], tri_b):
                return True, False
    return False, False


def _canonical_vertex_ids(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """(n, 3) per-face vertex ids after welding by position. Exported meshes
    duplicate vertices at UV/normal seams, so index-based adjacency misses
    neighbours that share an edge or corner in space."""
    scale = max(float(np.ptp(vertices, axis=0).max()) if len(vertices) else 1.0, 1e-12)
    keys = np.round(vertices / (scale * 1e-9)).astype(np.int64)
    _, inverse = np.unique(keys, axis=0, return_inverse=True)
    return inverse.reshape(-1)[faces]


def _in_wedge_2d(u: np.ndarray, w: np.ndarray, d: np.ndarray, eps: float) -> bool:
    def cross(x, y): return float(x[0] * y[1] - x[1] * y[0])
    span = cross(u, w)
    if abs(span) <= eps:
        return False
    sign = 1.0 if span > 0 else -1.0
    return cross(u, d) * sign > eps and cross(d, w) * sign > eps


def _shared_vertex_intersect(a: np.ndarray, b: np.ndarray, ia: int, ib: int, eps: float) -> tuple[bool, bool]:
    """Triangles a, b share exactly one vertex (a[ia] == b[ib]). True only if
    they overlap somewhere other than that shared point."""
    v = a[ia]
    a1, a2 = a[(ia + 1) % 3], a[(ia + 2) % 3]
    b1, b2 = b[(ib + 1) % 3], b[(ib + 2) % 3]
    na = np.cross(a1 - v, a2 - v)
    nb = np.cross(b1 - v, b2 - v)
    if np.linalg.norm(na) < eps or np.linalg.norm(nb) < eps:
        return False, False
    na /= np.linalg.norm(na)
    nb /= np.linalg.norm(nb)
    if np.linalg.norm(np.cross(na, nb)) <= 1e-9 and abs(float(np.dot(b1 - v, na))) <= eps and abs(float(np.dot(b2 - v, na))) <= eps:
        # coplanar: overlap iff the two corner wedges share interior directions
        keep = [i for i in range(3) if i != int(np.argmax(np.abs(na)))]
        ua, wa, ub, wb = (x[keep] - v[keep] for x in (a1, a2, b1, b2))
        bis_a, bis_b = ua / np.linalg.norm(ua) + wa / np.linalg.norm(wa), ub / np.linalg.norm(ub) + wb / np.linalg.norm(wb)
        e2 = eps * eps
        hit = (_in_wedge_2d(ua, wa, bis_b, e2) or _in_wedge_2d(ub, wb, bis_a, e2)
               or any(_in_wedge_2d(ua, wa, d, e2) for d in (ub, wb)) or any(_in_wedge_2d(ub, wb, d, e2) for d in (ua, wa)))
        return hit, True

    def far_point(p1, p2, plane_n):
        d1, d2 = float(np.dot(p1 - v, plane_n)), float(np.dot(p2 - v, plane_n))
        if (d1 > eps and d2 > eps) or (d1 < -eps and d2 < -eps):
            return None  # triangle meets the other plane only at v
        if abs(d1 - d2) <= eps:
            return None
        return p1 + (p2 - p1) * (d1 / (d1 - d2))

    pa = far_point(a1, a2, nb)
    pb = far_point(b1, b2, na)
    if pa is None or pb is None:
        return False, False
    da, db = pa - v, pb - v
    if np.linalg.norm(da) <= eps or np.linalg.norm(db) <= eps:
        return False, False
    # Both triangles' traces on the planes' intersection line start at v;
    # they overlap beyond v only if they point the same way.
    return float(np.dot(da, db)) > eps * eps, False


def _shared_edge_intersect(a: np.ndarray, b: np.ndarray, oa: int, ob: int, eps: float) -> tuple[bool, bool]:
    """Triangles share an edge; oa/ob index each one's opposite vertex. They
    overlap only if coplanar and folded onto the same side of the edge."""
    e0, e1 = a[(oa + 1) % 3], a[(oa + 2) % 3]
    n = np.cross(e1 - e0, a[oa] - e0)
    if np.linalg.norm(n) < eps:
        return False, False
    n /= np.linalg.norm(n)
    if abs(float(np.dot(b[ob] - e0, n))) > eps:
        return False, False
    side_a = float(np.dot(np.cross(e1 - e0, a[oa] - e0), n))
    side_b = float(np.dot(np.cross(e1 - e0, b[ob] - e0), n))
    return side_a * side_b > 0, True


def detect_exact_self_intersections(path: str | Path, *, max_pairs: int = 2000) -> ExactIntersectionReport:
    p = Path(path)
    mesh = trimesh.load(p, force="mesh", process=False)
    if not isinstance(mesh, trimesh.Trimesh):
        raise ValueError("single triangle mesh required")
    triangles = np.asarray(mesh.triangles)
    n = len(triangles)
    if n == 0:
        return ExactIntersectionReport(path=str(p), face_count=0, tested_pairs=0, intersecting_pair_count=0, intersecting_face_count=0, intersecting_ratio=0)
    ids = _canonical_vertex_ids(np.asarray(mesh.vertices, dtype=float), np.asarray(mesh.faces))
    eps = max(float(np.ptp(triangles.reshape(-1, 3), axis=0).max()), 1e-12) * 1e-9
    mins = triangles.min(axis=1); maxs = triangles.max(axis=1)
    pairs: list[ExactIntersectionPair] = []
    tested = 0; truncated = False
    chunk = 256
    for start in range(0, n, chunk):
        stop = min(n, start+chunk)
        overlap = (mins[start:stop,None,:] <= maxs[None,:,:]).all(2) & (maxs[start:stop,None,:] >= mins[None,:,:]).all(2)
        rows, cols = np.nonzero(overlap)
        for r, c in zip(rows.tolist(), cols.tolist()):
            a = start+r; b = c
            if b <= a: continue
            tested += 1
            shared = [(i, j) for i in range(3) for j in range(3) if ids[a][i] == ids[b][j]]
            if len(shared) >= 3:
                hit, coplanar = True, True  # duplicate face
            elif len(shared) == 2:
                oa = ({0, 1, 2} - {i for i, _ in shared}).pop(); ob = ({0, 1, 2} - {j for _, j in shared}).pop()
                hit, coplanar = _shared_edge_intersect(triangles[a], triangles[b], oa, ob, eps)
            elif len(shared) == 1:
                hit, coplanar = _shared_vertex_intersect(triangles[a], triangles[b], shared[0][0], shared[0][1], eps)
            else:
                hit, coplanar = triangles_intersect(triangles[a], triangles[b])
            if hit:
                pairs.append(ExactIntersectionPair(face_a=a, face_b=b, coplanar=coplanar))
                if len(pairs) >= max_pairs:
                    truncated = True; break
        if truncated: break
    faces = {x.face_a for x in pairs} | {x.face_b for x in pairs}
    warnings=[]
    if pairs:
        warnings.append("Exact triangle intersections detected; isolate and remesh or repair in a robust geometry kernel before displacement, rigging, or fabrication.")
    if truncated:
        warnings.append("Intersection report truncated at max_pairs; full repair pass should run in Blender or another robust kernel.")
    return ExactIntersectionReport(path=str(p), face_count=n, tested_pairs=tested, intersecting_pair_count=len(pairs), intersecting_face_count=len(faces), intersecting_ratio=len(faces)/n, pairs=pairs, truncated=truncated, warnings=warnings)


class ExactRepairPlan(BaseModel):
    intersecting_pair_count: int
    affected_face_count: int
    strategy: str
    destructive: bool
    requires_external_kernel: bool = True
    steps: list[str]


def compile_exact_intersection_repair_plan(report: ExactIntersectionReport) -> ExactRepairPlan:
    if report.intersecting_pair_count == 0:
        return ExactRepairPlan(intersecting_pair_count=0, affected_face_count=0, strategy="none", destructive=False, requires_external_kernel=False, steps=["No exact self-intersections detected."])
    if report.intersecting_pair_count <= 64 and report.intersecting_face_count <= 128:
        strategy = "localized_patch_remesh"
        steps = ["duplicate affected region", "preserve boundary loop", "remove intersecting faces", "localized remesh", "project detail from source", "re-run exact intersection QA"]
    else:
        strategy = "region_or_voxel_remesh"
        steps = ["isolate connected affected region", "preserve source as immutable reference", "robust remesh/boolean reconstruction", "reproject landmarks and surface detail", "re-run identity and exact intersection QA"]
    return ExactRepairPlan(intersecting_pair_count=report.intersecting_pair_count, affected_face_count=report.intersecting_face_count, strategy=strategy, destructive=True, steps=steps)
