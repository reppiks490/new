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


def test_meshy_preview_refine_endpoint_503_without_api_key(monkeypatch):
    monkeypatch.delenv("MESHY_API_KEY", raising=False)
    r = client.post("/v1/providers/meshy/preview-refine", json={"prompt": "a fictional adventurer"})
    assert r.status_code == 503


def test_meshy_preview_refine_endpoint_full_success_with_stubbed_client(monkeypatch):
    import app.main as main_module

    class _StubClient:
        def __init__(self, api_key):
            self.api_key = api_key

        def create_text_preview(self, prompt, **kwargs):
            return "preview-1"

        def create_text_refine(self, preview_task_id, **kwargs):
            return "refine-1"

        def query_text(self, task_id):
            from app.providers.execution import CanonicalTaskStatus, ProviderTaskSnapshot
            from app.providers.models import ProviderId
            return ProviderTaskSnapshot(provider=ProviderId.MESHY, task_id=task_id, status=CanonicalTaskStatus.SUCCEEDED)

    monkeypatch.setenv("MESHY_API_KEY", "test-key-not-real")
    monkeypatch.setattr(main_module, "MeshyClient", _StubClient)

    r = client.post("/v1/providers/meshy/preview-refine", json={"prompt": "a fictional adventurer", "poll_interval_seconds": 0})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "succeeded"
    assert body["preview_task_id"] == "preview-1"
    assert body["refine_task_id"] == "refine-1"


def test_plan_endpoint_attaches_render_job_by_default():
    r = client.post("/v1/plan", json={"character": {"prompt": "fictional adventurer"}})
    assert r.status_code == 200
    body = r.json()
    assert body["render"]["output"]["tier"] == "8k"


def test_plan_endpoint_accepts_custom_render_options():
    r = client.post("/v1/plan", json={
        "character": {"prompt": "fictional adventurer"},
        "hardware": {"vram_gb": 48, "ram_gb": 128},
        "render_quality_mode": "extreme",
        "render_resolution_tier": "16k",
    })
    assert r.status_code == 200
    assert r.json()["render"]["output"]["tier"] == "16k"


def test_plan_endpoint_with_reference_image_attaches_real_hints(tmp_path):
    from PIL import Image
    path = tmp_path / "ref.png"
    Image.new("RGB", (2048, 2048), color=(10, 20, 30)).save(path)
    r = client.post("/v1/plan", json={
        "character": {"prompt": "fictional adventurer"},
        "reference_image_path": str(path),
    })
    assert r.status_code == 200
    body = r.json()
    assert body["image_hints"]["width"] == 2048
    base = next(route for route in body["provider_routes"] if route["stage"] == "base_generation")
    assert base["required_capabilities"] == ["image_to_3d"]


def test_plan_endpoint_missing_reference_image_returns_404():
    r = client.post("/v1/plan", json={
        "character": {"prompt": "fictional adventurer"},
        "reference_image_path": "/nonexistent/ref.png",
    })
    assert r.status_code == 404


def test_plan_endpoint_rejects_invalid_resolution_tier():
    r = client.post("/v1/plan", json={
        "character": {"prompt": "fictional adventurer"},
        "render_resolution_tier": "not_a_real_tier",
    })
    assert r.status_code == 422


def test_tripo_generate_503_without_api_key(monkeypatch):
    monkeypatch.delenv("TRIPO_API_KEY", raising=False)
    r = client.post("/v1/providers/tripo/generate", json={"mode": "text", "prompt": "a fictional hero"})
    assert r.status_code == 503


def test_tripo_generate_422_for_unknown_mode(monkeypatch):
    monkeypatch.setenv("TRIPO_API_KEY", "test-key")
    r = client.post("/v1/providers/tripo/generate", json={"mode": "not_a_mode"})
    assert r.status_code == 422


def test_tripo_generate_422_for_text_mode_missing_prompt(monkeypatch):
    monkeypatch.setenv("TRIPO_API_KEY", "test-key")
    r = client.post("/v1/providers/tripo/generate", json={"mode": "text"})
    assert r.status_code == 422


def test_tripo_generate_full_success_with_stubbed_client(monkeypatch):
    import app.main as main_module
    from app.providers.execution import CanonicalTaskStatus, ProviderTaskSnapshot
    from app.providers.models import ProviderId

    class _StubClient:
        def __init__(self, api_key):
            pass

        def create_text(self, prompt, **kwargs):
            return "tripo-task-1"

        def query(self, task_id):
            return ProviderTaskSnapshot(provider=ProviderId.TRIPO, task_id=task_id, status=CanonicalTaskStatus.SUCCEEDED)

    monkeypatch.setenv("TRIPO_API_KEY", "test-key")
    monkeypatch.setattr(main_module, "TripoClient", _StubClient)
    r = client.post("/v1/providers/tripo/generate", json={"mode": "text", "prompt": "a fictional hero", "poll_interval_seconds": 0})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "succeeded"
    assert body["task_id"] == "tripo-task-1"


def test_hi3d_generate_503_without_api_key(monkeypatch):
    monkeypatch.delenv("HI3D_API_KEY", raising=False)
    r = client.post("/v1/providers/hi3d/generate", json={"image_path": "/tmp/whatever.png"})
    assert r.status_code == 503


def test_hi3d_generate_404_for_missing_local_image_even_with_api_key(monkeypatch):
    # The exact bug caught before shipping: verifies the 404 actually fires
    # for a missing local file, distinct from a soft-fail receipt.
    monkeypatch.setenv("HI3D_API_KEY", "test-key")
    r = client.post("/v1/providers/hi3d/generate", json={"image_path": "/definitely/not/a/real/path.png"})
    assert r.status_code == 404


def test_hi3d_generate_full_success_with_stubbed_client(monkeypatch, tmp_path):
    import app.main as main_module
    from app.providers.execution import CanonicalTaskStatus, ProviderTaskSnapshot
    from app.providers.hi3d import Hi3DSubmissionPlan
    from app.providers.models import ProviderId

    image_path = tmp_path / "ref.png"
    from PIL import Image
    Image.new("RGB", (64, 64), color=(1, 2, 3)).save(image_path)

    class _StubClient:
        def __init__(self, api_key):
            pass

        def create_image_file(self, image_path, *, face_count, output_format, callback_url=None):
            return "hi3d-task-1", Hi3DSubmissionPlan(requested_faces=face_count, retry_faces=(face_count,), resolution="2048quality")

        def query(self, task_id):
            return ProviderTaskSnapshot(provider=ProviderId.HI3D, task_id=task_id, status=CanonicalTaskStatus.SUCCEEDED)

    monkeypatch.setenv("HI3D_API_KEY", "test-key")
    monkeypatch.setattr(main_module, "Hi3DClient", _StubClient)
    r = client.post("/v1/providers/hi3d/generate", json={"image_path": str(image_path), "poll_interval_seconds": 0})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "succeeded"
    assert body["task_id"] == "hi3d-task-1"
