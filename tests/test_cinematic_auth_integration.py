"""Cinematic project API authorization and side-effect isolation.

These tests are intentionally independent of the batch/master feature branch.
They verify the existing local studio security contract on the original
cinematic orchestrator branch, without invoking render engines or the network.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


TOKEN = "test-owner-token"
UNKNOWN = "f" * 32
SCENE = "e" * 32
SHOT = "d" * 32


def _server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("CHARACTER3D_STUDIO_TOKEN", TOKEN)
    monkeypatch.setenv("CHARACTER3D_STUDIO_ORIGINS", "")
    for name in ("app.studio.server", "app.video.router"):
        sys.modules.pop(name, None)
    return importlib.import_module("app.studio.server")


def _project_payload():
    return {
        "title": "Private film",
        "master_prompt": "SENSITIVE_CANARY_NOT_FOR_ERROR_RESPONSES: scene in rain",
        "target_duration_seconds": 600,
        "delivery_fps": 24,
        "delivery_resolution": "1080p",
        "aspect_ratio": "16:9",
        "reference_image_ids": [],
    }


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/video/projects", None),
        ("POST", "/api/video/projects", _project_payload()),
        ("GET", f"/api/video/projects/{UNKNOWN}", None),
        ("PUT", f"/api/video/projects/{UNKNOWN}", {"expected_revision": 1, "title": "Leaked"}),
        ("POST", f"/api/video/projects/{UNKNOWN}/compile", {"expected_revision": 1}),
        ("GET", f"/api/video/projects/{UNKNOWN}/render-status", None),
        ("POST", f"/api/video/projects/{UNKNOWN}/render-missing", {"expected_revision": 1}),
        ("GET", f"/api/video/projects/{UNKNOWN}/masters", None),
        ("POST", f"/api/video/projects/{UNKNOWN}/assemble", {"expected_revision": 1}),
        ("GET", f"/api/video/projects/{UNKNOWN}/scenes/{SCENE}/shots/{SHOT}/plan", None),
        (
            "POST",
            f"/api/video/projects/{UNKNOWN}/scenes/{SCENE}/shots/{SHOT}/render",
            {"expected_revision": 1},
        ),
    ],
)
def test_every_project_render_and_master_route_requires_owner_bearer(
    monkeypatch, tmp_path, method, path, body
):
    server = _server(monkeypatch, tmp_path)
    with TestClient(server.app) as client:
        denied = client.request(method, path, json=body)
        wrong = client.request(method, path, json=body, headers={"Authorization": "Bearer incorrect"})
    for response in (denied, wrong):
        assert response.status_code == 401, response.text
        assert "SENSITIVE_CANARY_NOT_FOR_ERROR_RESPONSES" not in response.text
        assert TOKEN not in response.text


def test_denied_project_create_and_update_have_no_side_effects(monkeypatch, tmp_path):
    server = _server(monkeypatch, tmp_path)
    authorized = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(server.app) as client:
        denied_create = client.post("/api/video/projects", json=_project_payload())
        assert denied_create.status_code == 401
        initial = client.get("/api/video/projects", headers=authorized)
        assert initial.status_code == 200
        assert initial.json() == []

        create = client.post("/api/video/projects", json=_project_payload(), headers=authorized)
        assert create.status_code == 200, create.text
        project = create.json()
        denied_update = client.put(
            f"/api/video/projects/{project['id']}",
            json={"expected_revision": 1, "title": "Unauthorized edit"},
        )
        assert denied_update.status_code == 401
        persisted = client.get(f"/api/video/projects/{project['id']}", headers=authorized)
        assert persisted.status_code == 200
        assert persisted.json()["revision"] == 1
        assert persisted.json()["title"] == "Private film"


def test_foreign_origin_cannot_create_project_with_correct_token(monkeypatch, tmp_path):
    server = _server(monkeypatch, tmp_path)
    authorized = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(server.app) as client:
        cross_site = client.post(
            "/api/video/projects",
            json=_project_payload(),
            headers={**authorized, "Origin": "https://attacker.example"},
        )
        assert cross_site.status_code == 403, cross_site.text
        projects = client.get("/api/video/projects", headers=authorized)
        assert projects.status_code == 200
        assert projects.json() == []


@pytest.mark.parametrize(
    ("extension", "media_type"),
    [("png", "image/png"), ("mp4", "video/mp4")],
)
def test_private_media_assets_require_bearer_and_disallow_token_in_query(
    monkeypatch, tmp_path, extension, media_type
):
    server = _server(monkeypatch, tmp_path)
    storage = importlib.import_module("app.video.storage")
    asset_id = "a" * 32
    filename = f"{asset_id}.{extension}"
    private_bytes = b"PRIVATE_MEDIA_SENTINEL_NEVER_IN_ERROR_RESPONSES"
    storage.video_asset_path(asset_id, extension).write_bytes(private_bytes)
    route = f"/api/video/assets/{filename}"
    with TestClient(server.app) as client:
        no_token = client.get(route)
        bad_token = client.get(route, headers={"Authorization": "Bearer wrong"})
        query_token = client.get(route, params={"token": TOKEN})
        authorized = client.get(route, headers={"Authorization": f"Bearer {TOKEN}"})

    for rejected in (no_token, bad_token, query_token):
        assert rejected.status_code == 401
        assert private_bytes not in rejected.content
        assert TOKEN not in rejected.text
    assert authorized.status_code == 200
    assert authorized.content == private_bytes
    assert authorized.headers["content-type"].startswith(media_type)
    assert authorized.headers["cache-control"] == "no-store"



def test_rejected_master_operations_create_no_jobs_or_masters(monkeypatch, tmp_path):
    server = _server(monkeypatch, tmp_path)
    storage = importlib.import_module("app.video.storage")
    authorized = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(server.app) as client:
        create = client.post("/api/video/projects", json=_project_payload(), headers=authorized)
        assert create.status_code == 200, create.text
        project = create.json()
        project_id = project["id"]
        for endpoint in ("render-missing", "assemble"):
            denied = client.post(
                f"/api/video/projects/{project_id}/{endpoint}",
                json={"expected_revision": project["revision"]},
            )
            assert denied.status_code == 401, denied.text
            assert "SENSITIVE_CANARY_NOT_FOR_ERROR_RESPONSES" not in denied.text
        reloaded = client.get(f"/api/video/projects/{project_id}", headers=authorized)
        assert reloaded.status_code == 200
        assert reloaded.json()["revision"] == project["revision"]
    assert storage.list_video_records("video_job") == []
    assert storage.list_video_records("video_master") == []
