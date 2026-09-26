from pathlib import Path

import trimesh
from PIL import Image

from app.materials.udim import plan_character_udims
from app.providers.models import ProviderId
from app.qa.mesh import inspect_mesh
from app.qa.promotion import decide_promotion
from app.qa.textures import inspect_texture
from app.render.cycles import maximum_quality_preset


def test_mesh_inspector_on_generated_glb(tmp_path: Path):
    mesh = trimesh.creation.box(extents=(1, 2, 3))
    path = tmp_path / "box.glb"
    path.write_bytes(trimesh.exchange.gltf.export_glb(trimesh.Scene(mesh)))
    report = inspect_mesh(path)
    assert report.face_count == 12
    assert report.vertex_count > 0
    assert report.watertight
    assert report.degenerate_face_count == 0


def test_texture_inspector_detects_8k(tmp_path: Path):
    path = tmp_path / "map.png"
    Image.new("RGB", (8192, 8192)).save(path)
    report = inspect_texture(path)
    assert report.meets_8k
    assert report.max_dimension == 8192


def test_promotion_accepts_clean_untextured_mesh(tmp_path: Path):
    mesh = trimesh.creation.icosphere(subdivisions=2)
    path = tmp_path / "mesh.glb"
    path.write_bytes(trimesh.exchange.gltf.export_glb(trimesh.Scene(mesh)))
    qa = inspect_mesh(path)
    decision = decide_promotion(ProviderId.TRIPO, qa, [], target_faces=qa.face_count, pbr_channel_count=0)
    assert decision.accepted


def test_udim_plan_8k_has_large_memory_budget():
    plan = plan_character_udims(8, resolution=8192)
    assert len(plan.tiles) == 8
    assert plan.estimated_uncompressed_gib > 10
    assert plan.tiles[0].tile == 1001


def test_cycles_preset_scales_with_vram():
    hi = maximum_quality_preset(48, gpu_vendor="nvidia")
    lo = maximum_quality_preset(8, gpu_vendor="nvidia")
    assert hi.samples > lo.samples
    assert hi.subdivision_dicing_rate < lo.subdivision_dicing_rate
    assert hi.device == "OPTIX"
