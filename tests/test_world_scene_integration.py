from app.providers.provenance import sha256_file
from app.world.scene_integration import export_and_verify_world_scene, export_visible_world_tiles
from app.world.world_grid import WorldGridSpec, WorldStreamingManager


def _manager(**overrides):
    defaults = dict(
        name="isle", world_resolution_power=5, tile_count_x=2, tile_count_z=2,
        tile_size_meters=40.0, height_scale_meters=15.0, seed=9,
    )
    defaults.update(overrides)
    return WorldStreamingManager(WorldGridSpec(**defaults))


def test_visible_tiles_are_written_as_real_files_with_correct_hashes(tmp_path):
    mgr = _manager()
    scene, resolved = export_visible_world_tiles(mgr, (0.0, 0.0), view_distance_meters=200.0, output_dir=tmp_path)

    assert scene.assets
    assert len(resolved) == len(scene.assets)
    for instance in scene.assets:
        path = resolved[instance.instance_id]
        assert path.endswith(f"{instance.instance_id}.glb")
        # The instance's declared asset_sha256 must match the real file's
        # actual hash on disk, not just be some arbitrary-looking string.
        assert instance.asset_sha256 == sha256_file(path)


def test_tile_world_positions_are_placed_on_the_ground_plane_by_grid_index(tmp_path):
    mgr = _manager()
    scene, _resolved = export_visible_world_tiles(mgr, (0.0, 0.0), view_distance_meters=200.0, output_dir=tmp_path)
    by_id = {a.instance_id: a for a in scene.assets}
    assert by_id["terrain_tile_0_0"].transform.position == (0.0, 0.0, 0.0)
    assert by_id["terrain_tile_1_0"].transform.position == (40.0, 0.0, 0.0)
    assert by_id["terrain_tile_0_1"].transform.position == (0.0, 40.0, 0.0)


def test_full_pipeline_assembles_and_verifies_a_real_combined_scene(tmp_path):
    mgr = _manager()
    scene, resolved = export_visible_world_tiles(mgr, (0.0, 0.0), view_distance_meters=200.0, output_dir=tmp_path / "tiles")
    out = tmp_path / "combined_world.glb"

    report = export_and_verify_world_scene(scene, resolved, out)
    assert report.passed
    assert report.node_count == len(scene.assets)
    assert not report.blockers


def test_only_in_view_tiles_are_exported_not_the_whole_grid(tmp_path):
    mgr = _manager(tile_count_x=4, tile_count_z=4, tile_size_meters=40.0)
    scene, resolved = export_visible_world_tiles(mgr, (0.0, 0.0), view_distance_meters=30.0, output_dir=tmp_path)
    # A tight view distance from the origin should exclude most of a 4x4 grid.
    assert 0 < len(scene.assets) < 16
    assert len(resolved) == len(scene.assets)
