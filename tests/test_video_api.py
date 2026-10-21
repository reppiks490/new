from __future__ import annotations

import importlib
import io
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

MIB = 1024 * 1024
VALID_ID = "0123456789abcdef0123456789abcdef"


def _reload_server(monkeypatch, tmp_path: Path, *, token: str | None = None, origins: str = ""):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    if token is None:
        monkeypatch.delenv("CHARACTER3D_STUDIO_TOKEN", raising=False)
    else:
        monkeypatch.setenv("CHARACTER3D_STUDIO_TOKEN", token)
    monkeypatch.setenv("CHARACTER3D_STUDIO_ORIGINS", origins)
    for name in ["app.studio.server", "app.video.router"]:
        sys.modules.pop(name, None)
    return importlib.import_module("app.studio.server")


def _image_bytes(fmt: str, *, mode: str = "RGBA", size: tuple[int, int] = (24, 16)) -> bytes:
    image = Image.new(mode, size, (15, 40, 80, 150) if mode == "RGBA" else (15, 40, 80))
    if fmt == "JPEG" and image.mode != "RGB":
        image = image.convert("RGB")
    out = io.BytesIO()
    image.save(out, format=fmt)
    return out.getvalue()


def test_existing_studio_capabilities_remain_reachable(monkeypatch, tmp_path):
    server = _reload_server(monkeypatch, tmp_path)
    with TestClient(server.app) as client:
        response = client.get("/api/studio/capabilities")
    assert response.status_code == 200
    assert response.json()["backend"] is True


def test_video_capabilities_report_local_runtime(monkeypatch, tmp_path):
    server = _reload_server(monkeypatch, tmp_path)
    with TestClient(server.app) as client:
        response = client.get("/api/video/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert body["backend"] is True
    assert "runtime" in body
    assert "blockers" in body["runtime"]
    assert body["auth_required"] is False


def test_video_api_reuses_existing_bearer_auth(monkeypatch, tmp_path):
    server = _reload_server(monkeypatch, tmp_path, token="owner-token")
    with TestClient(server.app) as client:
        denied = client.get("/api/video/capabilities")
        allowed = client.get("/api/video/capabilities", headers={"Authorization": "Bearer owner-token"})
    assert denied.status_code == 401
    assert allowed.status_code == 200


def test_cors_allows_privacy_put_for_configured_mobile_origin(monkeypatch, tmp_path):
    server = _reload_server(monkeypatch, tmp_path, origins="https://phone.example")
    with TestClient(server.app) as client:
        response = client.options(
            "/api/video/privacy",
            headers={
                "Origin": "https://phone.example",
                "Access-Control-Request-Method": "PUT",
            },
        )
    assert response.status_code == 200
    assert "PUT" in response.headers["access-control-allow-methods"]


@pytest.mark.parametrize(
    ("fmt", "filename", "content_type"),
    [
        ("PNG", "source.png", "image/png"),
        ("JPEG", "source.jpg", "image/jpeg"),
        ("WEBP", "source.webp", "image/webp"),
    ],
)
def test_video_image_upload_accepts_supported_formats_and_normalizes_rgb_png(
    monkeypatch, tmp_path, fmt, filename, content_type
):
    server = _reload_server(monkeypatch, tmp_path)
    payload = _image_bytes(fmt)
    with TestClient(server.app) as client:
        response = client.post("/api/video/images", files={"file": (filename, payload, content_type)})
    assert response.status_code == 200
    body = response.json()
    assert len(body["image_id"]) == 32
    assert body["url"].endswith(f"{body['image_id']}.png")

    video_storage = importlib.import_module("app.video.storage")
    saved = video_storage.video_asset_path(body["image_id"], "png")
    with Image.open(saved) as image:
        assert image.format == "PNG"
        assert image.mode == "RGB"


def test_video_image_upload_rejects_more_than_12_mib(monkeypatch, tmp_path):
    server = _reload_server(monkeypatch, tmp_path)
    with TestClient(server.app) as client:
        response = client.post(
            "/api/video/images",
            files={"file": ("too-big.png", b"x" * (12 * MIB + 1), "image/png")},
        )
    assert response.status_code == 413


def test_video_image_upload_rejects_more_than_20_megapixels(monkeypatch, tmp_path):
    server = _reload_server(monkeypatch, tmp_path)
    payload = _image_bytes("PNG", mode="RGB", size=(5000, 4001))
    with TestClient(server.app) as client:
        response = client.post("/api/video/images", files={"file": ("huge.png", payload, "image/png")})
    assert response.status_code == 422


def test_video_image_upload_rejects_invalid_bytes(monkeypatch, tmp_path):
    server = _reload_server(monkeypatch, tmp_path)
    with TestClient(server.app) as client:
        response = client.post(
            "/api/video/images", files={"file": ("fake.png", b"not-an-image", "image/png")}
        )
    assert response.status_code == 422


def test_privacy_defaults_and_persistence(monkeypatch, tmp_path):
    server = _reload_server(monkeypatch, tmp_path)
    with TestClient(server.app) as client:
        initial = client.get("/api/video/privacy")
        changed = client.put(
            "/api/video/privacy",
            json={
                "privacy_mode": True,
                "mask_prompts": True,
                "blur_media": True,
                "quick_hide": False,
                "idle_lock_seconds": 15,
                "require_unlock_on_resume": True,
                "neutral_project_names": False,
            },
        )
        persisted = client.get("/api/video/privacy")
    assert initial.status_code == 200
    assert initial.json()["idle_lock_seconds"] == 30
    assert changed.status_code == 200
    assert persisted.json()["quick_hide"] is False
    assert persisted.json()["idle_lock_seconds"] == 15
    assert persisted.json()["neutral_project_names"] is False


def test_privacy_put_rejects_unknown_fields(monkeypatch, tmp_path):
    server = _reload_server(monkeypatch, tmp_path)
    with TestClient(server.app) as client:
        response = client.put("/api/video/privacy", json={"unexpected": True})
    assert response.status_code == 422


def test_mp4_asset_is_inline_video_and_never_cached(monkeypatch, tmp_path):
    server = _reload_server(monkeypatch, tmp_path)
    storage = importlib.import_module("app.video.storage")
    path = storage.video_asset_path(VALID_ID, "mp4")
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42test")
    with TestClient(server.app) as client:
        response = client.get(f"/api/video/assets/{VALID_ID}.mp4")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("video/mp4")
    assert response.headers["cache-control"] == "no-store"
    assert "attachment" not in response.headers.get("content-disposition", "").lower()


def test_internal_json_metadata_is_not_publicly_served(monkeypatch, tmp_path):
    server = _reload_server(monkeypatch, tmp_path)
    storage = importlib.import_module("app.video.storage")
    storage.video_asset_path(VALID_ID, "json").write_text("{}")
    with TestClient(server.app) as client:
        response = client.get(f"/api/video/assets/{VALID_ID}.json")
    assert response.status_code == 404


def test_missing_video_job_is_404(monkeypatch, tmp_path):
    server = _reload_server(monkeypatch, tmp_path)
    with TestClient(server.app) as client:
        response = client.get(f"/api/video/jobs/{VALID_ID}")
    assert response.status_code == 404


def test_generate_route_exists_but_does_not_fallback_to_cloud_before_worker(monkeypatch, tmp_path):
    server = _reload_server(monkeypatch, tmp_path)
    with TestClient(server.app) as client:
        response = client.post(
            "/api/video/generate",
            json={"image_id": VALID_ID, "prompt": "subtle movement"},
        )
    assert response.status_code == 503
    assert "local" in response.json()["detail"].lower()
