import trimesh

from app.qa.topology import analyze_obj_topology

# Hand-written OBJ with a known, exact face composition: 2 triangles, 3
# quads, 1 pentagon (n-gon). Vertex positions are arbitrary/unused by the
# parser -- only face vertex-reference counts matter for classification.
_MIXED_OBJ = """\
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
v 0 0 1
v 1 0 1
f 1 2 3
f 1 3 4
f 1 2 3 4
f 2 3 4 5
f 1 2 4 5
f 1 2 3 4 5
"""


def test_mixed_topology_counts_exactly(tmp_path):
    path = tmp_path / "mixed.obj"
    path.write_text(_MIXED_OBJ)
    report = analyze_obj_topology(path)
    assert report.triangle_count == 2
    assert report.quad_count == 3
    assert report.ngon_count == 1
    assert report.total_faces == 6


def test_ratios_sum_to_one_and_match_counts(tmp_path):
    path = tmp_path / "mixed.obj"
    path.write_text(_MIXED_OBJ)
    report = analyze_obj_topology(path)
    assert abs((report.triangle_ratio + report.quad_ratio + report.ngon_ratio) - 1.0) < 1e-9
    assert abs(report.quad_ratio - 3 / 6) < 1e-9


def test_quad_dominant_threshold_is_inclusive_of_half(tmp_path):
    # The fixture's quad_ratio is exactly 3/6 = 0.5, and quad_dominant uses
    # >=0.5, so this mesh must be quad_dominant.
    path = tmp_path / "mixed.obj"
    path.write_text(_MIXED_OBJ)
    report = analyze_obj_topology(path)
    assert report.quad_ratio == 0.5
    assert report.quad_dominant


def test_all_triangle_mesh_from_a_real_trimesh_export_is_100pct_triangles(tmp_path):
    # trimesh always triangulates internally, so an exported OBJ from any
    # Trimesh object is guaranteed all-triangle -- a real cross-check against
    # a genuinely different code path than the hand-written fixture above.
    mesh = trimesh.creation.box(extents=(1, 2, 3))
    path = tmp_path / "box.obj"
    mesh.export(path)
    report = analyze_obj_topology(path)
    assert report.quad_count == 0
    assert report.ngon_count == 0
    assert report.triangle_count == report.total_faces == len(mesh.faces)
    assert report.triangle_ratio == 1.0
    assert not report.quad_dominant


def test_missing_file_raises(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        analyze_obj_topology(tmp_path / "does_not_exist.obj")


def test_empty_file_warns_and_reports_zero_faces(tmp_path):
    path = tmp_path / "empty.obj"
    path.write_text("v 0 0 0\nv 1 0 0\nv 1 1 0\n")  # vertices only, no faces
    report = analyze_obj_topology(path)
    assert report.total_faces == 0
    assert any("No face lines" in w for w in report.warnings)


def test_effective_triangle_count_uses_exact_fan_triangulation(tmp_path):
    # Fixture: 2 triangles + 3 quads + 1 pentagon.
    # Exact cost: 2*(3-2) + 3*(4-2) + 1*(5-2) = 2 + 6 + 3 = 11.
    path = tmp_path / "mixed.obj"
    path.write_text(_MIXED_OBJ)
    report = analyze_obj_topology(path)
    assert report.effective_triangle_count == 11
    # Sanity: effective count must be >= raw face count whenever any
    # non-triangle face exists (a quad/n-gon never triangulates to fewer
    # than 1 triangle less than its own face count contributes).
    assert report.effective_triangle_count > report.total_faces


def test_effective_triangle_count_equals_face_count_for_all_triangle_mesh(tmp_path):
    import trimesh
    mesh = trimesh.creation.icosphere(subdivisions=1)
    path = tmp_path / "sphere.obj"
    mesh.export(path)
    report = analyze_obj_topology(path)
    # Every face is already a triangle (n-2=1 each), so effective count must
    # equal the raw face count exactly.
    assert report.effective_triangle_count == report.total_faces == len(mesh.faces)
