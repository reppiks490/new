"""QA112: strict Bearer scheme contract for the private Character3D API.

Only synthetic header strings and an unmapped API URL are used. This test
exercises the real FastAPI middleware, without media, inference or network IO.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

TOKEN = "qa112-disposable-test-only-secret"
UNMAPPED_API_PATH = "/api/__qa112_unmapped_probe__"


class RawSecretAcceptedWithoutBearer(AssertionError):
    """Narrow unresolved auth-scheme failure; unrelated assertions remain RED."""


@pytest.mark.xfail(
    raises=RawSecretAcceptedWithoutBearer,
    strict=True,
    reason="QA112: raw Authorization secret is accepted without Bearer scheme",
)
def test_private_api_requires_exact_bearer_scheme(monkeypatch):
    monkeypatch.setenv("CHARACTER3D_STUDIO_TOKEN", TOKEN)
    from app.studio.server import app

    # Unmapped route distinguishes middleware 401 from downstream 404, without
    # opening any owner project or media. No lifespan/startup is executed.
    client = TestClient(app)
    assert client.get(UNMAPPED_API_PATH).status_code == 401
    assert client.get(
        UNMAPPED_API_PATH, headers={"Authorization": "Bearer invalid"}
    ).status_code == 401
    assert client.get(
        UNMAPPED_API_PATH, headers={"Authorization": f"Bearer {TOKEN}"}
    ).status_code == 404

    # The only expected failure is acceptance of a raw secret lacking the
    # mandatory Bearer scheme. Strict XPASS flags a future production fix.
    raw = client.get(
        UNMAPPED_API_PATH, headers={"Authorization": TOKEN}
    )
    if raw.status_code != 401:
        raise RawSecretAcceptedWithoutBearer(
            f"raw Authorization credential reached downstream route: HTTP {raw.status_code}"
        )
