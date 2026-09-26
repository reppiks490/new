import numpy as np
import pytest

from app.world.world_grid import (
    WorldGridSpec,
    WorldStreamingManager,
    extract_tile_heightmap,
    generate_master_heightmap,
    tile_mesh,
)


def _spec(**overrides):
    defaults = dict(
        name="w", world_resolution_power=6, tile_count_x=4, tile_count_z=4,
        tile_size_meters=50.0, height_scale_meters=20.0, seed=5,
    )
    defaults.update(overrides)
    return WorldGridSpec(**defaults)


def test_non_divisible_tiling_is_rejected():
    with pytest.raises(ValueError):
        WorldGridSpec(name="w", world_resolution_power=6, tile_count_x=5, tile_count_z=4,
                       tile_size_meters=50.0, height_scale_meters=20.0)


def test_adjacent_tile_heightmaps_share_exact_boundary_values():
    spec = _spec()
    master = generate_master_heightmap(spec)
    t00 = extract_tile_heightmap(master, spec, 0, 0)
    t10 = extract_tile_heightmap(master, spec, 1, 0)
    t01 = extract_tile_heightmap(master, spec, 0, 1)
    # Exact equality, not "close" -- these are literally the same underlying
    # array values by construction (overlapping slice), so there is no
    # floating-point tolerance to reason about.
    assert np.array_equal(t00[:, -1], t10[:, 0])
    assert np.array_equal(t00[-1, :], t01[0, :])


def test_adjacent_tile_meshes_share_real_vertex_positions_at_the_seam():
    spec = _spec()
    master = generate_master_heightmap(spec)
    mesh_a = tile_mesh(master, spec, 0, 0)
    mesh_b = tile_mesh(master, spec, 1, 0)
    # tile (0,0)'s far-x edge vertices (x == tile_size_meters) must match
    # tile (1,0)'s near-x edge vertices (x == 0) after shifting tile_b by
    # one tile width, proving actual mesh geometry seams, not just the
    # underlying heightmap array.
    edge_a = mesh_a.vertices[np.isclose(mesh_a.vertices[:, 0], spec.tile_size_meters)]
    edge_b = mesh_b.vertices[np.isclose(mesh_b.vertices[:, 0], 0.0)]
    edge_a_sorted = edge_a[np.argsort(edge_a[:, 1])]
    edge_b_sorted = edge_b[np.argsort(edge_b[:, 1])]
    assert edge_a_sorted.shape == edge_b_sorted.shape
    assert np.allclose(edge_a_sorted[:, 2], edge_b_sorted[:, 2])  # matching heights at the seam


def test_lod_downsampling_is_an_exact_stride_subset_of_lod0():
    spec = _spec()
    master = generate_master_heightmap(spec)
    hm0 = extract_tile_heightmap(master, spec, 0, 0)
    mesh_lod0 = tile_mesh(master, spec, 0, 0, lod=0)
    mesh_lod1 = tile_mesh(master, spec, 0, 0, lod=1)
    assert len(mesh_lod1.vertices) < len(mesh_lod0.vertices)
    # LOD1's height values must be an exact stride-2 subset of the LOD0
    # heightmap, not a re-generated/approximated terrain.
    expected = hm0[::2, ::2].ravel() * spec.height_scale_meters
    assert np.allclose(np.sort(mesh_lod1.vertices[:, 2]), np.sort(expected))


def test_lod_for_distance_uses_configured_thresholds():
    spec = _spec()
    mgr = WorldStreamingManager(spec, lod_distances=(100.0, 300.0))
    assert mgr.lod_for_distance(50.0) == 0
    assert mgr.lod_for_distance(100.0) == 0
    assert mgr.lod_for_distance(150.0) == 1
    assert mgr.lod_for_distance(300.0) == 1
    assert mgr.lod_for_distance(500.0) == 2


def test_tiles_in_view_only_includes_tiles_within_distance():
    spec = _spec(tile_count_x=4, tile_count_z=4, tile_size_meters=100.0)
    mgr = WorldStreamingManager(spec)
    # Viewer at the world origin corner; only nearby tiles should qualify
    # for a small view distance.
    near = mgr.tiles_in_view((0.0, 0.0), view_distance_meters=80.0)
    far = mgr.tiles_in_view((0.0, 0.0), view_distance_meters=1000.0)
    assert (0, 0) in near
    assert (3, 3) not in near  # far corner, well outside 60m
    assert len(far) == spec.tile_count_x * spec.tile_count_z  # everything qualifies at 1000m


def test_update_loads_expected_tiles_and_evicts_out_of_view_tiles():
    spec = _spec(tile_count_x=4, tile_count_z=4, tile_size_meters=100.0)
    mgr = WorldStreamingManager(spec, lod_distances=(150.0, 400.0))

    loaded_near = mgr.update((0.0, 0.0), view_distance_meters=80.0)
    assert (0, 0) in loaded_near
    assert len(mgr._tile_cache) == len(loaded_near)

    # Move the viewer to the far corner tile's own center: tiles near the
    # origin should be evicted from the cache since a fresh update() no
    # longer needs them. (Verified with real distance math before picking
    # this position: (350, 350) is exactly tile (3,3)'s center, so it's the
    # only tile within an 80m view distance from there.)
    loaded_far = mgr.update((350.0, 350.0), view_distance_meters=80.0)
    assert (0, 0) not in loaded_far
    assert loaded_far.keys() == {(3, 3)}
    # Cache should only contain what the latest update actually needed.
    assert len(mgr._tile_cache) == len(loaded_far)


def test_out_of_range_tile_request_raises():
    spec = _spec()
    master = generate_master_heightmap(spec)
    with pytest.raises(ValueError):
        extract_tile_heightmap(master, spec, spec.tile_count_x, 0)
