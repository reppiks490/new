import trimesh
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_scene_plan_endpoint():
    r = client.post("/v1/scenes/plan", json={"scene": {"name": "s", "assets": []}, "hardware": {}})
    assert r.status_code == 200
    body = r.json()
    assert body["policy"]["allowed"]
    assert body["scene_manifest_hash"]


def test_scene_placement_qa_endpoint():
    r = client.post("/v1/scenes/placement-qa", json={"name": "s", "assets": []})
    assert r.status_code == 200
    assert r.json()["passed"]


def test_terrain_generate_endpoint_writes_a_real_file(tmp_path):
    out = tmp_path / "hills.glb"
    r = client.post("/v1/world/terrain/generate", json={
        "terrain": {"name": "hills", "size_meters": 50, "resolution_power": 4, "height_scale_meters": 10, "seed": 1},
        "output_path": str(out),
        "with_biomes": True,
    })
    assert r.status_code == 200
    assert out.is_file()
    assert r.json()["vertex_count"] > 0


def test_world_tile_generate_endpoint(tmp_path):
    out = tmp_path / "tile.glb"
    r = client.post("/v1/world/tile/generate", json={
        "world": {"name": "w", "world_resolution_power": 5, "tile_count_x": 2, "tile_count_z": 2,
                  "tile_size_meters": 40, "height_scale_meters": 15, "seed": 2},
        "tile_x": 0, "tile_z": 0, "output_path": str(out),
    })
    assert r.status_code == 200
    assert out.is_file()


def test_world_tile_generate_out_of_range_returns_422(tmp_path):
    out = tmp_path / "tile.glb"
    r = client.post("/v1/world/tile/generate", json={
        "world": {"name": "w", "world_resolution_power": 5, "tile_count_x": 2, "tile_count_z": 2,
                  "tile_size_meters": 40, "height_scale_meters": 15},
        "tile_x": 99, "tile_z": 0, "output_path": str(out),
    })
    assert r.status_code == 422


def test_body_morphs_apply_endpoint(tmp_path):
    in_path = tmp_path / "box.obj"
    trimesh.creation.box(extents=(1, 1, 1)).export(in_path)
    out_path = tmp_path / "morphed.obj"
    r = client.post("/v1/body-morphs/apply", json={
        "input_path": str(in_path), "output_path": str(out_path),
        "morphs": {"sliders": {"height": 1.0}},
        "region_weights": {"whole_body": [1.0] * 8},
    })
    assert r.status_code == 200
    assert out_path.is_file()


def test_render_job_compile_endpoint():
    r = client.post("/v1/render/job/compile", json={
        "vram_gb": 24, "ram_gb": 64, "quality_mode": "hero", "resolution_tier": "8k",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["output"]["width"] == 7680
    assert body["fits_hardware"]


def test_render_output_verify_endpoint_rejects_wrong_dimensions(tmp_path):
    from PIL import Image
    path = tmp_path / "small.jpg"
    Image.new("RGB", (100, 100), color=(1, 2, 3)).save(path)
    r = client.post("/v1/render/output/verify", json={"resolution_tier": "4k", "output_path": str(path)})
    assert r.status_code == 200
    assert not r.json()["meets_or_exceeds_spec"]


def test_topology_endpoint(tmp_path):
    path = tmp_path / "box.obj"
    trimesh.creation.box(extents=(1, 2, 3)).export(path)
    r = client.post("/v1/qa/topology", json={"path": str(path)})
    assert r.status_code == 200
    assert r.json()["triangle_count"] == 12


def test_topology_endpoint_missing_file_returns_404():
    r = client.post("/v1/qa/topology", json={"path": "/nonexistent/file.obj"})
    assert r.status_code == 404


def test_image_analysis_endpoint(tmp_path):
    from PIL import Image
    path = tmp_path / "flat.png"
    Image.new("RGB", (512, 512), color=(80, 90, 100)).save(path)
    r = client.post("/v1/pipeline/image-analysis", json={"path": str(path)})
    assert r.status_code == 200
    assert r.json()["width"] == 512


def test_hi3d_mode_fields_endpoint_portrait():
    r = client.post("/v1/providers/hi3d/mode-fields", json={"mode": "portrait", "face_count": 1_500_000})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "portrait"
    assert body["face"] == "1500000"


def test_hi3d_mode_fields_endpoint_unknown_mode_returns_422():
    r = client.post("/v1/providers/hi3d/mode-fields", json={"mode": "not_a_real_mode"})
    assert r.status_code == 422
