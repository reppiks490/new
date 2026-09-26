from __future__ import annotations

"""Real interactive 3D preview for generated meshes (terrain, morphed
characters, scene assets), via a live Three.js WebGL scene rather than a
static claim about a mesh's shape.

No GLTFLoader/OBJLoader is available in the viewer's JS sandbox (confirmed
via the tool's own documentation, not assumed) -- geometry is instead
serialized directly as a THREE.BufferGeometry from the mesh's real
vertex/face/vertex-color arrays, embedded as JS array literals in the
generated scene code.
"""

import json
from typing import Literal

import numpy as np
import trimesh

from app.core.axes import ZUP_TO_YUP


def _validate_finite(name: str, arr: np.ndarray) -> None:
    if not np.isfinite(arr).all():
        raise ValueError(f"{name} contains non-finite values (NaN/Inf); cannot serialize to valid JS")


def mesh_to_threejs_code(
    mesh: trimesh.Trimesh,
    *,
    background_hex: int = 0x1a1a2e,
    material_color_hex: int = 0x8899aa,
    wireframe: bool = False,
    up_axis: Literal["z", "y"] = "z",
) -> str:
    """Build Three.js scene-setup JS code for a real mesh: actual vertex
    positions, actual face indices, actual per-vertex colors when the mesh
    has them (e.g. biome-colored terrain from app.world.biomes), and a
    camera automatically framed to the mesh's real bounding box rather than
    a fixed distance that would put an arbitrarily-sized generated mesh
    off-screen or too small to see.

    up_axis is the input mesh's vertical axis. Three.js is Y-up, so a Z-up
    mesh (this project's internal convention) is rotated into Y-up before
    serializing -- otherwise terrain renders standing on its edge and
    OrbitControls orbits around the wrong axis.
    """
    if up_axis not in ("z", "y"):
        raise ValueError(f"up_axis must be 'z' or 'y', got {up_axis!r}")
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    if len(vertices) == 0 or len(faces) == 0:
        raise ValueError("mesh has no geometry to render")
    _validate_finite("vertices", vertices)
    if up_axis == "z":
        vertices = vertices @ ZUP_TO_YUP[:3, :3].T

    lo, hi = vertices.min(axis=0), vertices.max(axis=0)
    center = (lo + hi) / 2.0
    diagonal = float(np.linalg.norm(hi - lo)) or 1.0
    camera_distance = diagonal * 1.6

    # JSON is valid JS array-literal syntax for numeric arrays, so no custom
    # serialization is needed -- and json.dumps rejects NaN/Infinity by
    # default (allow_nan=False below), giving a clear error instead of
    # emitting invalid JS if the finite check above were ever bypassed.
    # Rounded to 5 decimals: the data lands in a Float32BufferAttribute
    # (~7 significant digits), so full float64 reprs only tripled payload.
    positions_flat = np.round(vertices, 5).ravel().tolist()
    indices_flat = faces.ravel().tolist()
    positions_json = json.dumps(positions_flat, allow_nan=False)
    indices_json = json.dumps(indices_flat, allow_nan=False)

    colors_snippet = ""
    vertex_colors = getattr(getattr(mesh, "visual", None), "vertex_colors", None)
    has_vertex_colors = vertex_colors is not None and len(vertex_colors) == len(vertices)
    if has_vertex_colors:
        # Mesh vertex colors are sRGB bytes; three.js (r152+ color
        # management) treats a color attribute as linear and encodes to sRGB
        # on output, so passing sRGB values through unconverted renders every
        # color visibly washed out.
        srgb = np.asarray(vertex_colors, dtype=np.float64)[:, :3] / 255.0
        linear = np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)
        colors_json = json.dumps(np.round(linear, 5).ravel().tolist(), allow_nan=False)
        colors_snippet = f"""
geometry.setAttribute('color', new THREE.Float32BufferAttribute({colors_json}, 3));"""

    material_snippet = (
        f"new THREE.MeshStandardMaterial({{ vertexColors: true, roughness: 0.85, wireframe: {str(wireframe).lower()} }})"
        if has_vertex_colors else
        f"new THREE.MeshStandardMaterial({{ color: {hex(material_color_hex)}, roughness: 0.6, wireframe: {str(wireframe).lower()} }})"
    )

    # Near/far scale with the mesh: a fixed 0.1 near plane against a far
    # plane sized for a multi-kilometer terrain destroys depth precision.
    near = max(diagonal * 1e-4, 1e-4)
    far = diagonal * 100.0
    cx, cy, cz = (float(c) for c in center)
    return f"""
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(50, width / height, {near:.6g}, {far:.6g});
const renderer = new THREE.WebGLRenderer({{ canvas, antialias: true, alpha: true }});
renderer.setSize(width, height);
renderer.setClearColor({hex(background_hex)}, 1);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.target.set({cx:.4f}, {cy:.4f}, {cz:.4f});

const geometry = new THREE.BufferGeometry();
geometry.setAttribute('position', new THREE.Float32BufferAttribute({positions_json}, 3));
geometry.setIndex({indices_json});
geometry.computeVertexNormals();{colors_snippet}

const material = {material_snippet};
const mesh = new THREE.Mesh(geometry, material);
scene.add(mesh);

scene.add(new THREE.HemisphereLight(0xdfe8ff, 0x3a3226, 1.1));
const sun = new THREE.DirectionalLight(0xfff4e0, 2.4);
sun.position.set({cx:.4f} + {diagonal:.4f}, {cy:.4f} + {diagonal * 1.2:.4f}, {cz:.4f} + {diagonal * 0.6:.4f});
sun.target.position.set({cx:.4f}, {cy:.4f}, {cz:.4f});
scene.add(sun);
scene.add(sun.target);

// Y-up: camera sits above and in front of the mesh, looking down at it.
camera.position.set(
  {cx:.4f} + {camera_distance:.4f} * 0.45,
  {cy:.4f} + {camera_distance:.4f} * 0.55,
  {cz:.4f} + {camera_distance:.4f} * 0.7
);
camera.lookAt({cx:.4f}, {cy:.4f}, {cz:.4f});

function animate() {{
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
}}
animate();
""".strip()
