from __future__ import annotations

import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient


def _reload_server(monkeypatch, tmp_path: Path, *, token: str | None = None):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    if token is None:
        monkeypatch.delenv("CHARACTER3D_STUDIO_TOKEN", raising=False)
    else:
        monkeypatch.setenv("CHARACTER3D_STUDIO_TOKEN", token)
    monkeypatch.setenv("CHARACTER3D_STUDIO_ORIGINS", "")
    for name in ["app.studio.server", "app.video.router"]:
        sys.modules.pop(name, None)
    return importlib.import_module("app.studio.server")


def _project_payload(prompt: str | None = None):
    return {
        "title": "Ten Minute Film",
        "master_prompt": prompt or "SCENE 1: Rooftop\nRain falls.\nSCENE 2: Alley\nShe runs into the alley.",
        "target_duration_seconds": 600,
        "delivery_fps": 120,
        "delivery_resolution": "2160p",
        "aspect_ratio": "16:9",
        "continuity_bible": {"wardrobe": "black coat", "weather": "rain"},
        "reference_image_ids": [],
    }


def test_project_routes_reuse_existing_bearer_auth(monkeypatch, tmp_path):
    server = _reload_server(monkeypatch, tmp_path, token="owner-token")
    with TestClient(server.app) as client:
        denied = client.get("/api/video/projects")
        allowed = client.get("/api/video/projects", headers={"Authorization": "Bearer owner-token"})
    assert denied.status_code == 401
    assert allowed.status_code == 200


def test_create_get_list_cinematic_project(monkeypatch, tmp_path):
    server = _reload_server(monkeypatch, tmp_path)
    with TestClient(server.app) as client:
        created = client.post("/api/video/projects", json=_project_payload())
        assert created.status_code == 200, created.text
        project = created.json()
        assert project["revision"] == 1
        assert len(project["id"]) == 32

        fetched = client.get(f"/api/video/projects/{project['id']}")
        listed = client.get("/api/video/projects")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == project["id"]
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [project["id"]]


def test_update_project_revision_conflict_returns_409(monkeypatch, tmp_path):
    server = _reload_server(monkeypatch, tmp_path)
    with TestClient(server.app) as client:
        project = client.post("/api/video/projects", json=_project_payload()).json()
        first = client.put(
            f"/api/video/projects/{project['id']}",
            json={"expected_revision": 1, "title": "Winner"},
        )
        stale = client.put(
            f"/api/video/projects/{project['id']}",
            json={"expected_revision": 1, "title": "Loser"},
        )
    assert first.status_code == 200
    assert first.json()["revision"] == 2
    assert stale.status_code == 409
    assert "revision" in stale.json()["detail"].lower()


def test_compile_project_returns_new_revision_and_preserves_explicit_scenes(monkeypatch, tmp_path):
    server = _reload_server(monkeypatch, tmp_path)
    with TestClient(server.app) as client:
        project = client.post("/api/video/projects", json=_project_payload()).json()
        response = client.post(
            f"/api/video/projects/{project['id']}/compile",
            json={
                "expected_revision": 1,
                "preferred_shot_seconds": 10,
                "engine_max_duration_seconds": 10,
            },
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["project"]["revision"] == 2
    assert body["diagnostics"]["mode"] == "explicit"
    assert [scene["title"] for scene in body["project"]["scenes"]] == ["Rooftop", "Alley"]
    assert body["diagnostics"]["shot_count"] == 60


def test_get_shot_plan_reports_native_and_delivery_settings_separately(monkeypatch, tmp_path):
    server = _reload_server(monkeypatch, tmp_path)
    engine = importlib.import_module("app.video.engine")
    engine._ENGINE_REGISTRY.clear()
    engine.register_engine(engine.FakeVideoEngine())
    with TestClient(server.app) as client:
        project = client.post("/api/video/projects", json=_project_payload()).json()
        compiled = client.post(
            f"/api/video/projects/{project['id']}/compile",
            json={"expected_revision": 1, "preferred_shot_seconds": 10, "engine_max_duration_seconds": 10},
        ).json()["project"]
        scene = compiled["scenes"][0]
        shot = scene["shots"][0]
        response = client.get(
            f"/api/video/projects/{project['id']}/scenes/{scene['scene_id']}/shots/{shot['shot_id']}/plan"
        )
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["generation_resolution"] == "1080p"
    assert plan["generation_fps"] == 60
    assert plan["delivery_resolution"] == "2160p"
    assert plan["delivery_fps"] == 120


def test_invalid_overlong_master_prompt_returns_422(monkeypatch, tmp_path):
    server = _reload_server(monkeypatch, tmp_path)
    with TestClient(server.app) as client:
        response = client.post("/api/video/projects", json=_project_payload("x" * 100_001))
    assert response.status_code == 422


def test_missing_project_is_404(monkeypatch, tmp_path):
    server = _reload_server(monkeypatch, tmp_path)
    with TestClient(server.app) as client:
        response = client.get("/api/video/projects/" + "f" * 32)
    assert response.status_code == 404
