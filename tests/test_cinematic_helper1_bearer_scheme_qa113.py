"""Helper 1 QA113: private API must reject bare secrets and non-Bearer auth.

Only disposable synthetic headers and a deliberately unmapped API URL are used.
No startup, private footage, external requests, or media generation.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

TOKEN = "helper1-qa113-disposable-secret"
PATH = "/api/__helper1_qa113_unmapped__"


@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize("header", [
    None,
    "Bearer wrong-secret",
    TOKEN,
    f"Basic {TOKEN}",
    f"Token {TOKEN}",
    f"Bearer  {TOKEN}",
])
def test_private_api_denies_non_bearer_and_raw_token(monkeypatch, method, header):
    monkeypatch.setenv("CHARACTER3D_STUDIO_TOKEN", TOKEN)
    from app.studio.server import app

    headers = {} if header is None else {"Authorization": header}
    response = TestClient(app).request(method, PATH, headers=headers)
    assert response.status_code == 401, (
        f"{method} must reject absent, malformed, or non-Bearer Authorization"
    )
    assert response.headers.get("cache-control") == "no-store"


@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize("scheme", ["Bearer", "bearer"])
def test_private_api_accepts_only_valid_bearer_credentials(monkeypatch, method, scheme):
    monkeypatch.setenv("CHARACTER3D_STUDIO_TOKEN", TOKEN)
    from app.studio.server import app

    response = TestClient(app).request(
        method, PATH, headers={"Authorization": f"{scheme} {TOKEN}"}
    )
    # A downstream 404 proves the bearer middleware accepted the credentials;
    # the intentionally unmapped path cannot disclose project or media data.
    assert response.status_code == 404
    assert response.headers.get("cache-control") == "no-store"
