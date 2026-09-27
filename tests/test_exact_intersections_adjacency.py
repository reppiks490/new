import numpy as np
import pytest
import trimesh

from app.qa.exact_intersections import detect_exact_self_intersections


def _count(tmp_path, mesh, name="m.obj"):
    path = tmp_path / name
    mesh.export(path)
    report = detect_exact_self_intersections(path)
    return report.intersecting_pair_count


def _tris(vertices, faces):
    return trimesh.Trimesh(vertices=np.asarray(vertices, float), faces=np.asarray(faces), process=False)


def test_clean_grid_neighbours_sharing_only_a_vertex_are_not_intersections(tmp_path):
    from app.world.terrain import TerrainSpec, generate_terrain_mesh

    assert _count(tmp_path, generate_terrain_mesh(TerrainSpec(name="t", size_meters=10, resolution_power=4, height_scale_meters=2))) == 0


def test_seam_split_vertices_are_welded_by_position(tmp_path):
    sphere = trimesh.creation.icosphere(subdivisions=2)
    split = _tris(sphere.vertices[sphere.faces.reshape(-1)], np.arange(len(sphere.faces) * 3).reshape(-1, 3))
    assert _count(tmp_path, split, "split.glb") == 0


def test_real_overlap_between_shells_is_found(tmp_path):
    a = trimesh.creation.icosphere(subdivisions=2)
    b = trimesh.creation.icosphere(subdivisions=2)
    b.apply_translation([1.9, 0, 0])
    assert _count(tmp_path, trimesh.util.concatenate([a, b]), "two.glb") > 0


def test_shared_vertex_triangles_that_pass_through_each_other(tmp_path):
    # both fan out from the origin; B pierces A's interior beyond the shared point
    mesh = _tris([[0, 0, 0], [2, 0, 0], [0, 2, 0], [1, 1, -1], [1, 1, 1]], [[0, 1, 2], [0, 3, 4]])
    assert _count(tmp_path, mesh) == 1


def test_shared_vertex_triangles_touching_only_at_that_vertex(tmp_path):
    mesh = _tris([[0, 0, 0], [2, 0, 0], [0, 2, 0], [-1, -1, 1], [-1, 0, 1]], [[0, 1, 2], [0, 3, 4]])
    assert _count(tmp_path, mesh) == 0


def test_shared_edge_fold_over_is_found_but_a_normal_crease_is_not(tmp_path):
    fold = _tris([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0.5, 0.5, 0]], [[0, 1, 2], [0, 1, 3]])
    crease = _tris([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0.5, -1, 0.3]], [[0, 1, 2], [0, 3, 1]])
    assert _count(tmp_path, fold, "fold.obj") == 1
    assert _count(tmp_path, crease, "crease.obj") == 0


def test_duplicate_face_is_found(tmp_path):
    dup = _tris([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 1, 2], [3, 4, 5]])
    assert _count(tmp_path, dup) == 1


def test_repair_acceptance_blocks_a_repair_that_opens_a_closed_surface():
    from app.qa.exact_intersections import ExactIntersectionReport
    from app.qa.identity_regions import WeightedIdentityReport
    from app.qa.mesh import MeshQAReport
    from app.qa.repair_acceptance import evaluate_repair_acceptance

    def mesh_report(watertight):
        return MeshQAReport(path="m", format="glb", face_count=10, vertex_count=8, geometry_count=1, body_count=1,
                            watertight=watertight, winding_consistent=True, degenerate_face_count=0, degenerate_face_ratio=0,
                            uv_vertex_ratio=0, surface_area=1, bounds_min=(0, 0, 0), bounds_max=(1, 1, 1), extents=(1, 1, 1))

    def inter(n):
        return ExactIntersectionReport(path="m", face_count=10, tested_pairs=10, intersecting_pair_count=n,
                                       intersecting_face_count=n, intersecting_ratio=min(n / 10, 1))

    identity = WeightedIdentityReport.model_construct(weighted_similarity=0.99, global_rms_error=0.01)
    opened = evaluate_repair_acceptance(inter(3), inter(0), mesh_report(True), mesh_report(False), identity)
    assert not opened.accepted and any("closed surface" in b for b in opened.blockers)
    sealed = evaluate_repair_acceptance(inter(3), inter(0), mesh_report(True), mesh_report(True), identity)
    assert sealed.accepted
