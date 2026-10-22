from __future__ import annotations

import importlib
import io
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

VALID_ID = "0123456789abcdef0123456789abcdef"


def _reload_server(monkeypatch, tmp_path: Path, *, token: str | None = None):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    if token is None:
        monkeypatch.delenv("CHARACTER3D_STUDIO_TOKEN", raising=False)
    else:
        monkeypatch.setenv("CHARACTER3D_STUDIO_TOKEN", token)
    for name in ["app.studio.server", "app.image.router"]:
        sys.modules.pop(name, None)
    return importlib.import_module("app.studio.server")


def _png_bytes() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (32, 24), (20, 40, 80)).save(out, format="PNG")
    return out.getvalue()


def test_image_capabilities_and_bearer_auth(monkeypatch, tmp_path):
    server = _reload_server(monkeypatch, tmp_path, token="owner-token")
    with TestClient(server.app) as client:
        denied = client.get("/api/image/capabilities")
        allowed = client.get("/api/image/capabilities", headers={"Authorization": "Bearer owner-token"})
    assert denied.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json()["backend"] is True
    assert "engines" in allowed.json()


def test_image_upload_generate_poll_and_private_png(monkeypatch, tmp_path):
    server = _reload_server(monkeypatch, tmp_path)
    from app.image import engine

    engine._ENGINE_REGISTRY.clear()
    engine.register_engine(engine.FakeImageEngine())

    with TestClient(server.app) as client:
        uploaded = client.post(
            "/api/image/images",
            files={"file": ("source.png", _png_bytes(), "image/png")},
        )
        assert uploaded.status_code == 200
        image_id = uploaded.json()["image_id"]

        queued = client.post(
            "/api/image/generate",
            json={"image_id": image_id, "prompt": "make the jacket red", "seed": 7},
        )
        assert queued.status_code == 200
        job = queued.json()
        assert job["status"] == "queued"
        assert "prompt" not in job

        deadline = time.time() + 10
        current = job
        while time.time() < deadline:
            current = client.get(f"/api/image/jobs/{job['id']}").json()
            if current["status"] in {"succeeded", "failed"}:
                break
            time.sleep(0.05)
        assert current["status"] == "succeeded", current
        assert "prompt" not in current
        assert current["asset_url"].endswith(".png")

        result = client.get(current["asset_url"])
        assert result.status_code == 200
        assert result.headers["content-type"].startswith("image/png")
        assert result.headers["cache-control"] == "no-store"


def test_image_generate_rejects_missing_source(monkeypatch, tmp_path):
    server = _reload_server(monkeypatch, tmp_path)
    from app.image import engine

    engine._ENGINE_REGISTRY.clear()
    engine.register_engine(engine.FakeImageEngine())
    with TestClient(server.app) as client:
        response = client.post(
            "/api/image/generate",
            json={"image_id": VALID_ID, "prompt": "make it cinematic"},
        )
    assert response.status_code == 422


def test_server_startup_interrupts_preexisting_image_jobs(monkeypatch, tmp_path):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    storage = importlib.import_module("app.image.storage")
    pending = storage.put_image_record("image_job", {"status": "queued", "stage": "Queued", "progress": 0})
    server = _reload_server(monkeypatch, tmp_path)
    with TestClient(server.app):
        pass
    stored = storage.get_image_record("image_job", pending["id"])
    assert stored["status"] == "failed"
    assert stored["stage"] == "Interrupted"
