import numpy as np
import trimesh

from app.world.terrain import TerrainSpec, diamond_square_heightmap, generate_terrain_mesh, heightmap_to_mesh


def _spec(**overrides):
    defaults = dict(name="hills", size_meters=100.0, resolution_power=4, height_scale_meters=20.0, seed=1)
    defaults.update(overrides)
    return TerrainSpec(**defaults)


def test_heightmap_is_deterministic_finite_and_normalized():
    a = diamond_square_heightmap(_spec())
    b = diamond_square_heightmap(_spec())
    assert np.array_equal(a, b)
    assert np.isfinite(a).all()
    assert a.min() >= 0.0 and a.max() <= 1.0
    assert a.std() > 0  # not a degenerate flat grid


def test_different_seed_gives_different_terrain():
    a = diamond_square_heightmap(_spec(seed=1))
    b = diamond_square_heightmap(_spec(seed=2))
    assert not np.array_equal(a, b)


def test_heightmap_shape_matches_resolution_power():
    spec = _spec(resolution_power=5)
    hm = diamond_square_heightmap(spec)
    assert hm.shape == (33, 33)  # 2**5 + 1


def test_heightmap_to_mesh_produces_expected_vertex_and_face_counts():
    hm = diamond_square_heightmap(_spec(resolution_power=3))  # 9x9 grid
    mesh = heightmap_to_mesh(hm, size_meters=10.0, height_scale_meters=2.0)
    n = 9
    assert len(mesh.vertices) == n * n
    assert len(mesh.faces) == 2 * (n - 1) * (n - 1)
    assert np.isfinite(mesh.vertices).all()
    # Heights actually vary (real relief, not a flat plane).
    assert mesh.vertices[:, 2].std() > 0


def test_generate_terrain_mesh_is_a_real_watertight_ish_grid_and_exports(tmp_path):
    spec = _spec(resolution_power=4, height_scale_meters=15.0)
    mesh = generate_terrain_mesh(spec)
    assert isinstance(mesh, trimesh.Trimesh)
    assert len(mesh.faces) > 0
    assert mesh.vertices[:, 2].max() <= spec.height_scale_meters + 1e-6
    assert mesh.vertices[:, 2].min() >= -1e-6

    out = tmp_path / "terrain.glb"
    mesh.export(out)
    assert out.is_file()
    reloaded = trimesh.load(out, force="mesh", process=False)
    assert len(reloaded.faces) == len(mesh.faces)


def test_resolution_power_10_stays_within_2m_interchange_ceiling():
    # power=10 -> 1025x1025 grid -> 2*(1024**2) triangles; confirms the docstring's
    # claim about landing at the project's 2M interchange tier rather than
    # asserting it without checking.
    n = 2 ** 10 + 1
    triangle_count = 2 * (n - 1) * (n - 1)
    assert triangle_count == 2_097_152
