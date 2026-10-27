"""QA103: strict no-store denial for a genuine 600s private cinematic master.

Test-first acceptance for a known QA102 false-positive: a defaulted header
lookup can silently pass even if an unauthorized HTTP response has no
Cache-Control header. Real synthetic FFmpeg media, no owner assets.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
from pathlib import Path
import shutil
import sys

import pytest
from fastapi.testclient import TestClient


pytestmark = pytest.mark.skipif(
    os.environ.get("CINEMATIC_600S_DENIAL_CACHE_QA") != "1",
    reason="600-second genuine-media private denial cache QA is opt-in",
)


class MissingNoStoreOnUnauthorizedMaster(AssertionError):
    """401 Range denial omitted explicit no-store protection."""


def _synthetic_600s_master(monkeypatch, tmp_path: Path):
    # Reuse the frozen QA102 media builder without editing its agent-owned file.
    source = Path(__file__).with_name("test_cinematic_600s_private_http_range_qa102.py")
    spec = importlib.util.spec_from_file_location("cinematic_qa102_fixture", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._master(monkeypatch, tmp_path), module.TOKEN


def test_unauthorized_600s_range_explicitly_disables_caching(monkeypatch, tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.fail("Opt-in genuine-media QA requires FFmpeg and FFprobe")
    (master, route), token = _synthetic_600s_master(monkeypatch, tmp_path)
    assert master.is_file() and master.stat().st_size > 4096

    # Test the real application middleware, not a mocked response.
    for name in ("app.studio.server", "app.video.router"):
        sys.modules.pop(name, None)
    server = importlib.import_module("app.studio.server")
    with TestClient(server.app) as client:
        for headers, params in (
            ({"Range": "bytes=0-1023"}, None),
            ({"Authorization": "Bearer invalid", "Range": "bytes=0-1023"}, None),
            ({"Range": "bytes=-1024"}, {"token": token}),
        ):
            response = client.get(route, headers=headers, params=params)
            assert response.status_code == 401
            assert token not in response.text
            # Do not supply a fallback value: missing headers must fail.
            actual = response.headers.get("cache-control")
            if actual != "no-store":
                raise MissingNoStoreOnUnauthorizedMaster(
                    f"Private master 401 Range denial must send Cache-Control: "
                    f"no-store, got {actual!r}"
                )

    # This is a server-side synthetic media privacy contract, not proof of
    # actual mobile browser cache behavior or physical device playback.
