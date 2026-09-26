from __future__ import annotations

from pathlib import Path

from app.core.scene_models import AssetKind, SceneAssetInstance, SceneSpec, Transform
from app.exports.scene_export import ResolvedSceneAsset, SceneExportReport, assemble_scene_glb, validate_scene_export
from app.providers.provenance import sha256_file
from app.world.world_grid import WorldStreamingManager

# Ground-plane axis convention (fixed by app.world.terrain.heightmap_to_mesh):
# tile-local X/Y are the ground plane, Z is height. tile_x/tile_z here are
# grid *indices*, and are placed onto world X/Y respectively -- "z" in
# tile_z/viewer_xz is the streaming manager's own naming (borrowed from
# common game-dev ground-plane-is-XZ convention) and does NOT mean this
# project's vertical axis, which stays Z=height everywhere else in this repo.


def export_visible_world_tiles(
    manager: WorldStreamingManager,
    viewer_xz: tuple[float, float],
    view_distance_meters: float,
    output_dir: str | Path,
) -> tuple[SceneSpec, dict[str, str]]:
    """Bridge world-tile streaming to real scene composition: for every tile
    currently in view, actually write a real GLB file to disk, hash it, and
    place it as a SceneAssetInstance at its correct world-space position.
    Returns (SceneSpec, resolved_paths) -- resolved_paths is local
    filesystem state (where each instance's file actually landed on THIS
    machine), deliberately kept separate from the SceneSpec itself rather
    than stashed as a hidden attribute on it: SceneSpec is meant to be a
    portable/serializable description, and a local path map wouldn't
    survive a model_dump()/round-trip, so pretending it lived on the model
    would silently break the moment someone persisted or shared the spec.
    Every returned instance corresponds to a real file already on disk with
    a real SHA-256, verified below by export_and_verify_world_scene.
    """
    tiles = manager.update(viewer_xz, view_distance_meters)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    instances: list[SceneAssetInstance] = []
    resolved: dict[str, str] = {}
    for (tile_x, tile_z), mesh in tiles.items():
        instance_id = f"terrain_tile_{tile_x}_{tile_z}"
        path = out_dir / f"{instance_id}.glb"
        mesh.export(path)
        digest = sha256_file(path)
        instances.append(SceneAssetInstance(
            instance_id=instance_id,
            asset_kind=AssetKind.ENVIRONMENT,
            asset_sha256=digest,
            transform=Transform(position=(
                tile_x * manager.spec.tile_size_meters,
                tile_z * manager.spec.tile_size_meters,
                0.0,
            )),
            display_name=f"{manager.spec.name} tile ({tile_x}, {tile_z})",
            viewport_triangles=len(mesh.faces),
            hero_source_triangles=len(mesh.faces),
        ))
        resolved[instance_id] = str(path)

    scene = SceneSpec(
        name=f"{manager.spec.name}_visible_region",
        prompt="",
        assets=instances,
        bounds_meters=(
            manager.spec.tile_count_x * manager.spec.tile_size_meters,
            manager.spec.tile_count_z * manager.spec.tile_size_meters,
            manager.spec.height_scale_meters * 2,
        ),
    )
    return scene, resolved


def export_and_verify_world_scene(
    scene: SceneSpec, resolved_paths: dict[str, str], output_path: str | Path,
) -> SceneExportReport:
    """Assemble the per-tile files export_visible_world_tiles wrote into one
    combined multi-tile GLB, and verify it -- reusing the already-real,
    already-tested app.exports.scene_export pipeline rather than a parallel
    world-specific export path."""
    resolved_assets = [
        ResolvedSceneAsset(instance=instance, mesh_path=resolved_paths[instance.instance_id])
        for instance in scene.assets
        if instance.instance_id in resolved_paths
    ]
    assembled = assemble_scene_glb(scene, resolved_assets, output_path)
    if not assembled.passed:
        return assembled
    return validate_scene_export(scene, output_path)
