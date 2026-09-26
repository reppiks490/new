from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import trimesh
from pydantic import BaseModel, Field

from app.core.axes import ZUP_TO_YUP, is_gltf_path, load_mesh_zup, scene_node_matrix_for_file
from app.core.scene_models import SceneAssetInstance, SceneSpec, Transform

# Confirmed against the installed trimesh version (not assumed): a GLB export/
# import round-trip preserves node_name, and Scene.graph[node_name] returns
# (4x4 transform matrix, internal geometry key). See BUILD_LOG session 5 for
# the probe that established this before writing code against it.


def _rot_x(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _rot_y(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _rot_z(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def transform_matrix(t: Transform) -> np.ndarray:
    """Deterministic 4x4 TRS matrix for a Transform: scale, then intrinsic XYZ
    Euler rotation, then translation (v' = R @ S @ v + T). This is this
    project's own fixed convention, applied identically on write (scene
    assembly) and read (export validation) — it is not claimed to bit-for-bit
    match any specific external tool's Euler handedness without a Blender-side
    cross-check, which this environment cannot run.
    """
    rx, ry, rz = (math.radians(a) for a in t.rotation_euler_deg)
    rot = _rot_z(rz) @ _rot_y(ry) @ _rot_x(rx)
    scale = np.diag(t.scale)
    m = np.eye(4)
    m[:3, :3] = rot @ scale
    m[:3, 3] = t.position
    return m


class ResolvedSceneAsset(BaseModel):
    instance: SceneAssetInstance
    mesh_path: str  # local path to an already-generated/validated single-asset mesh


class SceneExportReport(BaseModel):
    output_path: str
    node_count: int
    matches_declared_instance_count: bool
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.matches_declared_instance_count and not self.blockers


def assemble_scene_glb(
    scene: SceneSpec,
    resolved_assets: list[ResolvedSceneAsset],
    output_path: str | Path,
) -> SceneExportReport:
    """Combine each resolved per-instance mesh into one multi-node glTF/GLB
    scene, placed at its declared SceneAssetInstance.transform. This is real,
    local, executed geometry work (trimesh) — not a synthetic/planned stage —
    consistent with this project's execution-truth discipline
    (docs/V10_EXECUTION_TRUTH.md): if this function returns a passed report,
    the file was actually written and actually contains that many nodes.
    """
    declared_ids = {a.instance_id for a in scene.assets}
    resolved_ids = {r.instance.instance_id for r in resolved_assets}
    blockers: list[str] = []
    warnings: list[str] = []

    missing = declared_ids - resolved_ids
    extra = resolved_ids - declared_ids
    if missing:
        blockers.append(f"Missing resolved mesh for declared instance(s): {sorted(missing)}")
    if extra:
        warnings.append(f"Resolved mesh(es) not declared in the scene spec: {sorted(extra)}")

    out = Path(output_path)
    combined = trimesh.Scene()
    for resolved in resolved_assets:
        mesh_path = Path(resolved.mesh_path)
        if not mesh_path.is_file():
            blockers.append(f"{resolved.instance.instance_id}: resolved mesh path does not exist: {mesh_path}")
            continue
        loaded = load_mesh_zup(mesh_path)
        if not isinstance(loaded, trimesh.Trimesh) or len(loaded.faces) == 0:
            blockers.append(f"{resolved.instance.instance_id}: resolved mesh has no triangle geometry.")
            continue
        # Scene transforms are Z-up (this project's convention). For a glTF
        # output, geometry goes in as C @ g and each node as C @ T @ C^-1, so
        # the file's world-space result is C @ T @ g: the spec-correct Y-up
        # image of the Z-up scene. Asset files are read through the same
        # boundary, so provider GLBs (Y-up) stand upright next to terrain.
        geometry = loaded
        if is_gltf_path(out):
            geometry = loaded.copy()
            geometry.apply_transform(ZUP_TO_YUP)
        combined.add_geometry(
            geometry,
            node_name=resolved.instance.instance_id,
            transform=scene_node_matrix_for_file(transform_matrix(resolved.instance.transform), out),
        )

    if blockers:
        return SceneExportReport(
            output_path=str(out),
            node_count=len(combined.geometry),
            matches_declared_instance_count=False,
            blockers=blockers,
            warnings=warnings,
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    combined.export(out)
    return SceneExportReport(
        output_path=str(out),
        node_count=len(combined.geometry),
        matches_declared_instance_count=len(combined.geometry) == len(declared_ids),
        warnings=warnings,
    )


def validate_scene_export(
    scene: SceneSpec,
    output_path: str | Path,
    *,
    transform_atol: float = 1e-4,
) -> SceneExportReport:
    """Reopen an exported scene file and cross-check it against the SceneSpec
    that was supposed to produce it: every declared instance present as a
    node, no undeclared extra nodes silently added, and each node's transform
    matches the declared Transform (not just "some file exists with N meshes").
    """
    out = Path(output_path)
    if not out.is_file():
        return SceneExportReport(
            output_path=str(out), node_count=0, matches_declared_instance_count=False,
            blockers=[f"{out} does not exist."],
        )

    loaded = trimesh.load(out, force="scene", process=False)
    if not isinstance(loaded, trimesh.Scene):
        return SceneExportReport(
            output_path=str(out), node_count=0, matches_declared_instance_count=False,
            blockers=["Export did not load as a multi-node scene."],
        )

    declared: dict[str, SceneAssetInstance] = {a.instance_id: a for a in scene.assets}
    blockers: list[str] = []
    warnings: list[str] = []
    found: set[str] = set()

    for node_name in loaded.graph.nodes_geometry:
        found.add(node_name)
        if node_name not in declared:
            warnings.append(f"Scene file contains node {node_name!r} not declared in the SceneSpec.")
            continue
        matrix, _geometry_key = loaded.graph[node_name]
        expected = scene_node_matrix_for_file(transform_matrix(declared[node_name].transform), out)
        if not np.allclose(matrix, expected, atol=transform_atol):
            blockers.append(f"Node {node_name!r} transform does not match its declared SceneSpec transform.")

    missing = set(declared) - found
    if missing:
        blockers.append(f"Declared instance(s) missing from the exported scene: {sorted(missing)}")

    return SceneExportReport(
        output_path=str(out),
        node_count=len(found),
        matches_declared_instance_count=not missing,
        blockers=blockers,
        warnings=warnings,
    )
