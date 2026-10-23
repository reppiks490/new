"""QA20: authenticated byte-range and HEAD readiness for large private masters.

This is a transport-only contract using deterministic sparse placeholder bytes,
NOT a playable MP4, FFmpeg decode, model inference, or an owner-device test.
The >80 MiB fixture is sparse and only tiny ranges are requested; no full-file
response is downloaded. Lead #40 owns the router; mobile #28 owns the client.
"""
from __future__ import annotations

import importlib
import sys

from fastapi.testclient import TestClient


TOKEN = "qa20-local-synthetic-bearer"
ASSET_ID = "a" * 32
ASSET_URL = f"/api/video/assets/{ASSET_ID}.mp4"
FILE_BYTES = 100 * 1024 * 1024 + 4096
MARKER_OFFSET = 90 * 1024 * 1024
MARKER = b"QA20RANGE"


def _private_asset(monkeypatch, tmp_path):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("CHARACTER3D_STUDIO_TOKEN", TOKEN)
    monkeypatch.setenv("CHARACTER3D_STUDIO_ORIGINS", "")
    from app.video.storage import video_asset_path

    path = video_asset_path(ASSET_ID, "mp4")
    # Sparse fixture: no 100 MiB allocation and no real codec claims.
    with path.open("wb") as handle:
        handle.truncate(FILE_BYTES)
        handle.seek(MARKER_OFFSET)
        handle.write(MARKER)

    for name in ("app.studio.server", "app.video.router"):
        sys.modules.pop(name, None)
    return importlib.import_module("app.studio.server").app


def test_large_private_asset_supports_bounded_authenticated_byte_ranges(monkeypatch, tmp_path):
    app = _private_asset(monkeypatch, tmp_path)
    auth = {"Authorization": f"Bearer {TOKEN}"}
    first = MARKER_OFFSET
    last = first + len(MARKER) - 1

    with TestClient(app) as client:
        for unauthorized in (
            client.get(ASSET_URL, headers={"Range": f"bytes={first}-{last}"}),
            client.get(ASSET_URL, params={"token": TOKEN}, headers={"Range": f"bytes={first}-{last}"}),
            client.get(ASSET_URL, headers={"Authorization": "Bearer invalid", "Range": f"bytes={first}-{last}"}),
        ):
            assert unauthorized.status_code == 401
            assert MARKER not in unauthorized.content
            assert TOKEN.encode() not in unauthorized.content

        response = client.get(ASSET_URL, headers={**auth, "Range": f"bytes={first}-{last}"})
        assert response.status_code == 206, response.text[:120]
        assert response.content == MARKER
        assert response.headers["content-range"] == f"bytes {first}-{last}/{FILE_BYTES}"
        assert response.headers["content-length"] == str(len(MARKER))
        assert response.headers["content-type"].startswith("video/mp4")
        assert response.headers["accept-ranges"] == "bytes"
        assert response.headers["cache-control"] == "no-store"

        # A second seek into the same >80 MiB master must not fetch its body.
        suffix = client.get(ASSET_URL, headers={**auth, "Range": "bytes=-8"})
        assert suffix.status_code == 206
        assert suffix.content == bytes(8)
        assert suffix.headers["content-length"] == "8"

        impossible = client.get(
            ASSET_URL, headers={**auth, "Range": f"bytes={FILE_BYTES}-{FILE_BYTES + 1}"}
        )
        assert impossible.status_code == 416
        assert len(impossible.content) < 256


def test_private_master_head_preflight_exposes_size_without_downloading_body(monkeypatch, tmp_path):
    """Known gap: FastAPI GET registration alone does not register HEAD.

    Mobile callers need an authenticated metadata-only preflight before choosing
    a bounded preview versus a future private streaming path. Keep this test RED
    until the router owner explicitly supports HEAD with identical auth.
    """
    app = _private_asset(monkeypatch, tmp_path)
    auth = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(app) as client:
        denied = client.head(ASSET_URL)
        assert denied.status_code == 401
        assert denied.content == b""

        response = client.head(ASSET_URL, headers=auth)
        assert response.status_code == 200
        assert response.content == b""
        assert response.headers["content-length"] == str(FILE_BYTES)
        assert response.headers["content-type"].startswith("video/mp4")
        assert response.headers["accept-ranges"] == "bytes"
        assert response.headers["cache-control"] == "no-store"
