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

import numpy as np
import trimesh


def _validate_finite(name: str, arr: np.ndarray) -> None:
    if not np.isfinite(arr).all():
        raise ValueError(f"{name} contains non-finite values (NaN/Inf); cannot serialize to valid JS")


def mesh_to_threejs_code(
    mesh: trimesh.Trimesh,
    *,
    background_hex: int = 0x1a1a2e,
    material_color_hex: int = 0x8899aa,
    wireframe: bool = False,
) -> str:
    """Build Three.js scene-setup JS code for a real mesh: actual vertex
    positions, actual face indices, actual per-vertex colors when the mesh
    has them (e.g. biome-colored terrain from app.world.biomes), and a
    camera automatically framed to the mesh's real bounding box rather than
    a fixed distance that would put an arbitrarily-sized generated mesh
    off-screen or too small to see.
    """
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    if len(vertices) == 0 or len(faces) == 0:
        raise ValueError("mesh has no geometry to render")
    _validate_finite("vertices", vertices)

    bounds = mesh.bounds
    center = (bounds[0] + bounds[1]) / 2.0
    diagonal = float(np.linalg.norm(bounds[1] - bounds[0])) or 1.0
    camera_distance = diagonal * 1.6

    # JSON is valid JS array-literal syntax for numeric arrays, so no custom
    # serialization is needed -- and json.dumps rejects NaN/Infinity by
    # default (allow_nan=False below), giving a clear error instead of
    # emitting invalid JS if the finite check above were ever bypassed.
    positions_flat = vertices.ravel().tolist()
    indices_flat = faces.ravel().tolist()
    positions_json = json.dumps(positions_flat, allow_nan=False)
    indices_json = json.dumps(indices_flat, allow_nan=False)

    colors_snippet = ""
    vertex_colors = getattr(getattr(mesh, "visual", None), "vertex_colors", None)
    has_vertex_colors = vertex_colors is not None and len(vertex_colors) == len(vertices)
    if has_vertex_colors:
        colors_arr = np.asarray(vertex_colors, dtype=np.float64)[:, :3] / 255.0
        colors_json = json.dumps(colors_arr.ravel().tolist(), allow_nan=False)
        colors_snippet = f"""
geometry.setAttribute('color', new THREE.Float32BufferAttribute({colors_json}, 3));"""

    material_snippet = (
        f"new THREE.MeshStandardMaterial({{ vertexColors: true, roughness: 0.85, wireframe: {str(wireframe).lower()} }})"
        if has_vertex_colors else
        f"new THREE.MeshStandardMaterial({{ color: {hex(material_color_hex)}, roughness: 0.6, wireframe: {str(wireframe).lower()} }})"
    )

    return f"""
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(60, width / height, 0.1, {camera_distance * 100:.1f});
const renderer = new THREE.WebGLRenderer({{ canvas, antialias: true, alpha: true }});
renderer.setSize(width, height);
renderer.setClearColor({hex(background_hex)}, 1);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.target.set({center[0]:.4f}, {center[1]:.4f}, {center[2]:.4f});

const geometry = new THREE.BufferGeometry();
geometry.setAttribute('position', new THREE.Float32BufferAttribute({positions_json}, 3));
geometry.setIndex({indices_json});
geometry.computeVertexNormals();{colors_snippet}

const material = {material_snippet};
const mesh = new THREE.Mesh(geometry, material);
scene.add(mesh);

scene.add(new THREE.DirectionalLight(0xffffff, 0.9).translateX(1).translateY(1).translateZ(1));
scene.add(new THREE.AmbientLight(0x606060, 0.8));

camera.position.set(
  {center[0]:.4f} + {camera_distance:.4f} * 0.6,
  {center[1]:.4f} - {camera_distance:.4f} * 0.8,
  {center[2]:.4f} + {camera_distance:.4f} * 0.5
);
camera.lookAt({center[0]:.4f}, {center[1]:.4f}, {center[2]:.4f});

function animate() {{
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
}}
animate();
""".strip()
