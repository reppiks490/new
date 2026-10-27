"""QA112: strict Bearer scheme contract for the private Character3D API.

Only synthetic header strings and an unmapped API URL are used. This test
exercises the real FastAPI middleware, without media, inference or network IO.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

TOKEN = "qa112-disposable-test-only-secret"
UNMAPPED_API_PATH = "/api/__qa112_unmapped_probe__"


def test_private_api_requires_exact_bearer_scheme(monkeypatch):
    monkeypatch.setenv("CHARACTER3D_STUDIO_TOKEN", TOKEN)
    from app.studio.server import app

    # Unmapped route intentionally distinguishes middleware 401 from downstream
    # 404, avoiding media or project data. No lifespan/startup is executed.
    client = TestClient(app)
    assert client.get(UNMAPPED_API_PATH).status_code == 401
    assert client.get(
        UNMAPPED_API_PATH, headers={"Authorization": "Bearer invalid"}
    ).status_code == 401
    assert client.get(
        UNMAPPED_API_PATH, headers={"Authorization": f"Bearer {TOKEN}"}
    ).status_code == 404

    # RED on QA111: middleware strips an optional prefix, so a raw secret
    # without the mandatory Bearer scheme is accepted as authenticated.
    assert client.get(
        UNMAPPED_API_PATH, headers={"Authorization": TOKEN}
    ).status_code == 401
