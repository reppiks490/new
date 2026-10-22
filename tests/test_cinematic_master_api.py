from __future__ import annotations

import importlib
import sys

from fastapi.testclient import TestClient


def _server(monkeypatch, tmp_path, *, token=None):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("CHARACTER3D_STUDIO_ORIGINS", "")
    if token is None:
        monkeypatch.delenv("CHARACTER3D_STUDIO_TOKEN", raising=False)
    else:
        monkeypatch.setenv("CHARACTER3D_STUDIO_TOKEN", token)
    for name in ("app.studio.server", "app.video.router"):
        sys.modules.pop(name, None)
    return importlib.import_module("app.studio.server").app


def _create(client, headers=None):
    response = client.post(
        "/api/video/projects",
        json={
            "title": "Film",
            "master_prompt": "PRIVATE_MASTER_PROMPT_DO_NOT_RETURN IN STATUS",
            "target_duration_seconds": 600,
            "delivery_fps": 120,
            "delivery_resolution": "2160p",
            "aspect_ratio": "16:9",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_project_master_routes_require_existing_studio_bearer_auth(monkeypatch, tmp_path):
    with TestClient(_server(monkeypatch, tmp_path, token="private-owner-token")) as client:
        headers = {"Authorization": "Bearer private-owner-token"}
        project = _create(client, headers=headers)
        root = f"/api/video/projects/{project['id']}"
        for url in (f"{root}/render-status", f"{root}/masters"):
            assert client.get(url).status_code == 401
            assert client.get(url, headers=headers).status_code == 200
        for url, payload in (
            (f"{root}/render-missing", {"expected_revision": 1}),
            (f"{root}/assemble", {"expected_revision": 1}),
        ):
            assert client.post(url, json=payload).status_code == 401
        result = client.get(f"{root}/render-status", headers=headers)
        assert "PRIVATE_MASTER_PROMPT_DO_NOT_RETURN" not in result.text


def test_master_assembly_requires_real_completed_shots_and_never_creates_fabricated_video(monkeypatch, tmp_path):
    with TestClient(_server(monkeypatch, tmp_path)) as client:
        project = _create(client)
        root = f"/api/video/projects/{project['id']}"
        status = client.get(f"{root}/render-status")
        assert status.status_code == 200
        assert status.json()["ready_for_assembly"] is False
        assert status.json()["total_shots"] == 0
        assert client.get(f"{root}/masters").json() == []
        response = client.post(f"{root}/assemble", json={"expected_revision": 1, "ffmpeg_path": "ffmpeg"})
        assert response.status_code == 409
        assert client.get(f"{root}/masters").json() == []
        assert list((tmp_path / "video-assets").glob("*.mp4")) == []
        stale = client.post(f"{root}/render-missing", json={"expected_revision": 99})
        assert stale.status_code == 409


def test_batch_empty_project_is_a_noop_and_does_not_advance_revision(monkeypatch, tmp_path):
    with TestClient(_server(monkeypatch, tmp_path)) as client:
        project = _create(client)
        root = f"/api/video/projects/{project['id']}"
        result = client.post(f"{root}/render-missing", json={"expected_revision": 1})
        assert result.status_code == 200, result.text
        payload = result.json()
        assert payload["jobs"] == []
        assert payload["skipped"] == 0
        assert payload["project"]["revision"] == 1
        assert client.get(f"{root}/render-status").json()["missing"] == 0
