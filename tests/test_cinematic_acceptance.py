from __future__ import annotations

import importlib
import io
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image


def _reload_server(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("CHARACTER3D_STUDIO_TOKEN", raising=False)
    monkeypatch.setenv("CHARACTER3D_STUDIO_ORIGINS", "")
    for name in ["app.studio.server", "app.video.router"]:
        sys.modules.pop(name, None)
    return importlib.import_module("app.studio.server")


def _png(rgb: tuple[int, int, int]) -> bytes:
    image = Image.new("RGB", (32, 24), rgb)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _wait_job(client: TestClient, job_id: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    current = {}
    while time.time() < deadline:
        response = client.get(f"/api/video/jobs/{job_id}")
        assert response.status_code == 200, response.text
        current = response.json()
        if current.get("status") in {"succeeded", "failed"}:
            return current
        time.sleep(0.05)
    pytest.fail(f"job {job_id} did not finish: {current}")


def test_exact_ten_minute_multiscene_project_renders_selected_shot_and_preserves_quick_generate(
    monkeypatch, tmp_path: Path
):
    server = _reload_server(monkeypatch, tmp_path)
    engine = importlib.import_module("app.video.engine")
    engine._ENGINE_REGISTRY.clear()
    engine.register_engine(engine.FakeVideoEngine())

    with TestClient(server.app) as client:
        refs = []
        for index, rgb in enumerate(((20, 30, 40), (80, 40, 20), (30, 90, 60)), start=1):
            response = client.post(
                "/api/video/images",
                files={"file": (f"ref-{index}.png", _png(rgb), "image/png")},
            )
            assert response.status_code == 200, response.text
            refs.append(response.json()["image_id"])
        ref_a, ref_b, ref_c = refs

        created = client.post(
            "/api/video/projects",
            json={
                "title": "Ten Minute Acceptance Film",
                "master_prompt": (
                    "SCENE 1: Rooftop\nA woman crosses a rain-soaked rooftop under blue moonlight.\n"
                    "SCENE 2: Alley\nShe descends into a narrow neon alley while the storm intensifies.\n"
                    "SCENE 3: Station\nShe reaches an old station and turns toward the arriving train."
                ),
                "target_duration_seconds": 600,
                "delivery_fps": 120,
                "delivery_resolution": "2160p",
                "aspect_ratio": "16:9",
                "continuity_bible": {
                    "characters": "same adult woman, exact facial identity",
                    "wardrobe": "black coat",
                    "lighting": "blue moonlight",
                    "freeform_notes": {"identity": "locked"},
                },
                "reference_image_ids": [ref_a, ref_b],
            },
        )
        assert created.status_code == 200, created.text
        project = created.json()
        assert project["revision"] == 1

        compiled_response = client.post(
            f"/api/video/projects/{project['id']}/compile",
            json={
                "expected_revision": 1,
                "preferred_shot_seconds": 10,
                "engine_max_duration_seconds": 10,
                "engine_name": "fake",
            },
        )
        assert compiled_response.status_code == 200, compiled_response.text
        compiled = compiled_response.json()
        project = compiled["project"]
        assert project["revision"] == 2
        assert compiled["diagnostics"]["scene_count"] == 3
        assert compiled["diagnostics"]["shot_count"] == 60

        shots = [shot for scene in project["scenes"] for shot in scene["shots"]]
        assert len(shots) == 60
        assert sum(float(shot["duration_seconds"]) for shot in shots) == pytest.approx(600.0, abs=1e-6)
        assert all(0 < float(shot["duration_seconds"]) <= 10 for shot in shots)

        scenes = project["scenes"]
        last_scene = scenes[-1]
        last_scene["continuity_patch"] = {
            "weather": "heavy rain",
            "location": "old station platform",
            "freeform_notes": {"camera": "slow handheld push"},
        }
        last_scene["reference_image_ids"] = [ref_b, ref_c]
        last_shot = last_scene["shots"][-1]
        last_shot["continuity_patch"] = {
            "wardrobe": "red coat",
            "story_state": "train doors opening",
            "freeform_notes": {"identity": "exact face lock", "mood": "urgent"},
        }
        last_shot["reference_image_ids"] = [ref_c, ref_a]

        updated_response = client.put(
            f"/api/video/projects/{project['id']}",
            json={"expected_revision": 2, "scenes": scenes},
        )
        assert updated_response.status_code == 200, updated_response.text
        project = updated_response.json()
        assert project["revision"] == 3
        last_scene = project["scenes"][-1]
        last_shot = last_scene["shots"][-1]

        plan_response = client.get(
            f"/api/video/projects/{project['id']}/scenes/{last_scene['scene_id']}/shots/{last_shot['shot_id']}/plan",
            params={"engine_name": "fake"},
        )
        assert plan_response.status_code == 200, plan_response.text
        plan = plan_response.json()
        assert plan["reference_image_ids"] == [ref_a, ref_b, ref_c]
        assert plan["effective_continuity"]["wardrobe"] == "red coat"
        assert plan["effective_continuity"]["weather"] == "heavy rain"
        assert plan["effective_continuity"]["lighting"] == "blue moonlight"
        assert plan["effective_continuity"]["location"] == "old station platform"
        assert plan["effective_continuity"]["story_state"] == "train doors opening"
        assert plan["generation_resolution"] == "1080p"
        assert plan["generation_fps"] == 60
        assert plan["delivery_resolution"] == "2160p"
        assert plan["delivery_fps"] == 120

        render_response = client.post(
            f"/api/video/projects/{project['id']}/scenes/{last_scene['scene_id']}/shots/{last_shot['shot_id']}/render",
            json={"expected_revision": 3, "engine_name": "fake"},
        )
        assert render_response.status_code == 200, render_response.text
        cinematic_job = render_response.json()["job"]
        finished = _wait_job(client, cinematic_job["id"])
        assert finished["status"] == "succeeded", finished
        assert finished["project_id"] == project["id"]
        assert finished["scene_id"] == last_scene["scene_id"]
        assert finished["shot_id"] == last_shot["shot_id"]
        assert "prompt" not in finished

        quick_response = client.post(
            "/api/video/generate",
            json={
                "image_id": ref_a,
                "prompt": "subtle natural motion",
                "engine_profile": "balanced",
                "duration_seconds": 5,
                "fps": 24,
                "resolution": "1080p",
            },
        )
        assert quick_response.status_code == 200, quick_response.text
        quick_finished = _wait_job(client, quick_response.json()["id"])
        assert quick_finished["status"] == "succeeded", quick_finished
