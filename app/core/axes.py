from __future__ import annotations

"""Single source of truth for up-axis handling at file I/O boundaries.

This project is Z-up internally (terrain heights, body-morph height bands,
scene transforms -- see app/world/scene_integration.py). glTF 2.0 mandates
Y-up ("glTF uses a right-handed coordinate system... +Y is up"), and every
provider this project routes to (Tripo, Meshy, Hi3D) returns glTF/GLB.
Converting at the boundary -- exactly what Blender's own glTF importer and
exporter do -- keeps internal math in one convention while every .glb/.gltf
written is spec-correct and every provider .glb read is interpreted with its
real vertical axis.

OBJ/STL/PLY carry no mandated up axis; they default to this project's
internal Z-up (unchanged prior behavior) and can be overridden per call.
"""

from pathlib import Path
from typing import Literal

import numpy as np
import trimesh

UpAxis = Literal["auto", "y", "z"]

GLTF_SUFFIXES = frozenset({".glb", ".gltf"})

# Proper rotation of -90 degrees about X: (x, y, z)_zup -> (x, z, -y)_yup.
# det = +1, so triangle winding (and therefore face orientation) is preserved.
ZUP_TO_YUP = np.array(
    [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, -1.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
)
YUP_TO_ZUP = ZUP_TO_YUP.T  # a rotation's inverse is its transpose


def is_gltf_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in GLTF_SUFFIXES


def resolve_up_axis(path: str | Path, up_axis: UpAxis = "auto") -> Literal["y", "z"]:
    if up_axis == "auto":
        return "y" if is_gltf_path(path) else "z"
    if up_axis not in ("y", "z"):
        raise ValueError(f"up_axis must be 'auto', 'y', or 'z', got {up_axis!r}")
    return up_axis


def load_mesh_zup(path: str | Path, up_axis: UpAxis = "auto") -> trimesh.Trimesh:
    """Load a mesh file into this project's internal Z-up convention."""
    mesh = trimesh.load(path, force="mesh", process=False)
    if resolve_up_axis(path, up_axis) == "y":
        mesh.apply_transform(YUP_TO_ZUP)
    return mesh


def export_mesh_from_zup(mesh: trimesh.Trimesh, path: str | Path, up_axis: UpAxis = "auto") -> None:
    """Write an internal Z-up mesh to disk in the file format's own
    convention (Y-up for glTF). Never mutates the caller's mesh."""
    out = mesh.copy()
    if resolve_up_axis(path, up_axis) == "y":
        out.apply_transform(ZUP_TO_YUP)
    out.export(path)


def scene_node_matrix_for_file(zup_matrix: np.ndarray, path: str | Path) -> np.ndarray:
    """A node transform expressed in a Z-up world, re-expressed for the
    target file's convention: C @ T @ C^-1 for glTF, unchanged otherwise.
    Paired with geometry converted by C, the file's world-space result is
    C @ T @ g -- the Y-up image of the Z-up scene."""
    if not is_gltf_path(path):
        return zup_matrix
    return ZUP_TO_YUP @ zup_matrix @ YUP_TO_ZUP
