"""Helper 1: exact local Host allowlist for tokenless cinematic API.

Test-first guard for the conditional DNS-rebinding weakness already reproduced
with genuine synthetic H.264 in draft PR #75. This file uses only an isolated
temporary SQLite workspace and does not access owner media or start workers.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    "host",
    [
        "cinema.attacker.invalid",
        "localhost.evil.invalid",
        "127.0.0.1.evil.invalid",
        "localhost..",
        "localhost:bad",
        "localhost:0",
        "localhost:65536",
        "[::1].evil.invalid",
    ],
)
def test_tokenless_loopback_rejects_untrusted_or_malformed_host(
    monkeypatch, tmp_path, host,
):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("CHARACTER3D_STUDIO_TOKEN", raising=False)
    server = importlib.import_module("app.studio.server")
    with TestClient(
        server.app, base_url="http://localhost",
        client=("127.0.0.1", 43001),
    ) as client:
        response = client.get("/api/video/projects", headers={"Host": host})
    assert response.status_code == 403, (host, response.status_code)


@pytest.mark.parametrize(
    "host",
    ["localhost", "localhost:8000", "127.0.0.1", "127.0.0.1:8000",
     "[::1]", "[::1]:8000"],
)
def test_tokenless_loopback_preserves_explicit_local_hosts(
    monkeypatch, tmp_path, host,
):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("CHARACTER3D_STUDIO_TOKEN", raising=False)
    server = importlib.import_module("app.studio.server")
    with TestClient(
        server.app, base_url="http://localhost",
        client=("127.0.0.1", 43002),
    ) as client:
        response = client.get("/api/video/projects", headers={"Host": host})
    assert response.status_code == 200, (host, response.status_code)


def test_default_testclient_and_authenticated_remote_still_work(
    monkeypatch, tmp_path,
):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("CHARACTER3D_STUDIO_TOKEN", raising=False)
    server = importlib.import_module("app.studio.server")
    with TestClient(server.app) as testclient:
        assert testclient.get("/api/video/projects").status_code == 200

    monkeypatch.setenv("CHARACTER3D_STUDIO_TOKEN", "synthetic-host-policy-token")
    with TestClient(
        server.app, base_url="http://cinema.attacker.invalid",
        client=("198.51.100.24", 43003),
    ) as remote:
        assert remote.get(
            "/api/video/projects",
            headers={"Authorization": "Bearer synthetic-host-policy-token"},
        ).status_code == 200
        assert remote.get("/api/video/projects").status_code == 401


@pytest.mark.parametrize(
    "host_headers",
    [
        [("Host", "localhost"), ("Host", "cinema.attacker.invalid")],
        [("Host", "cinema.attacker.invalid"), ("Host", "localhost")],
        [("Host", "localhost"), ("Host", "localhost")],
    ],
)
def test_tokenless_local_api_rejects_ambiguous_duplicate_host_headers(
    monkeypatch, tmp_path, host_headers,
):
    """No intermediary-dependent first/last Host interpretation is safe."""
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("CHARACTER3D_STUDIO_TOKEN", raising=False)
    server = importlib.import_module("app.studio.server")
    with TestClient(
        server.app, base_url="http://localhost",
        client=("127.0.0.1", 43004),
    ) as client:
        response = client.get("/api/video/projects", headers=host_headers)
        assert response.status_code == 403, (host_headers, response.status_code)
        # An ambiguous Host must not reach any state-changing API either.
        attempted_write = client.post(
            "/api/video/projects",
            headers=host_headers,
            json={"title": "should never persist"},
        )
        assert attempted_write.status_code == 403, (
            host_headers, attempted_write.status_code,
        )


@pytest.mark.parametrize(
    ("peer", "host", "expected"),
    [
        ("127.0.0.1", "testserver", 403),
        ("198.51.100.24", "localhost", 403),
        ("testclient", "cinema.attacker.invalid", 403),
        ("testclient", "testserver", 200),
    ],
)
def test_tokenless_testserver_exception_is_bound_to_synthetic_asgi_peer(
    monkeypatch, tmp_path, peer, host, expected,
):
    """The test-only hostname cannot become a real loopback exemption."""
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("CHARACTER3D_STUDIO_TOKEN", raising=False)
    server = importlib.import_module("app.studio.server")
    with TestClient(
        server.app, base_url="http://localhost",
        client=(peer, 43005),
    ) as client:
        response = client.get("/api/video/projects", headers={"Host": host})
    assert response.status_code == expected, (peer, host, response.status_code)
