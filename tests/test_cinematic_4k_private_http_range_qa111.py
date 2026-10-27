"""QA111: real synthetic 4K Character3D master via authenticated HTTP Range.

Disposable FFmpeg colors only. In-process FastAPI TestClient exercises real
middleware/FileResponse, not a networked phone, browser, owner PC, or model.
"""
from __future__ import annotations

import hashlib
import importlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient


pytestmark = pytest.mark.skipif(
    os.environ.get("CINEMATIC_4K_PRIVATE_RANGE_QA111") != "1",
    reason="opt-in real synthetic 4K private HTTP Range acceptance",
)
TOKEN = "qa111-disposable-synthetic-token"


def _run(args: list[str], timeout: int = 180) -> None:
    subprocess.run(args, check=True, capture_output=True, timeout=timeout)


def _create_4k_master(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("CHARACTER3D_STUDIO_TOKEN", TOKEN)
    monkeypatch.setenv("CHARACTER3D_STUDIO_ORIGINS", "")

    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    storage = importlib.import_module("app.video.storage")
    requests = importlib.import_module("app.video.cinematic_requests")

    asset_ids = []
    for i, color in enumerate(("red", "blue")):
        asset_id = f"{5110 + i:032x}"
        path = storage.video_asset_path(asset_id, "mp4")
        _run([
            "ffmpeg", "-nostdin", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=320x180:r=24:d=1",
            "-an", "-c:v", "mpeg4", "-q:v", "4", str(path),
        ], timeout=90)
        assert path.is_file() and path.stat().st_size > 1000
        asset_ids.append(asset_id)

    project = service.create_project(models.ProjectCreateRequest(
        title="QA111 disposable 4K private delivery",
        master_prompt="Synthetic FFmpeg colors only; no owner media.",
        target_duration_seconds=10, delivery_fps=24,
        delivery_resolution="2160p", aspect_ratio="16:9",
    ))
    shots = [
        models.CinematicShot(
            shot_id=f"{5120 + i:032x}", ordinal=i + 1,
            title=f"Disposable color {i + 1}", prompt="Synthetic color",
            duration_seconds=5.0,
        )
        for i in range(2)
    ]
    scene = models.CinematicScene(
        scene_id="b" * 32, ordinal=1, title="Private 4K range",
        target_duration_seconds=10, shots=shots,
    )
    project = service.update_project(
        project.id, models.ProjectUpdateRequest(
            expected_revision=1, scenes=[scene],
        ),
    )
    linked = []
    for shot, asset_id in zip(project.scenes[0].shots, asset_ids):
        record = storage.put_video_record("video_job", {
            "status": "succeeded", "project_id": project.id,
            "scene_id": scene.scene_id, "shot_id": shot.shot_id,
            "project_revision": project.revision, "asset_id": asset_id,
            "asset_url": f"/api/video/assets/{asset_id}.mp4",
        })
        linked.append(shot.model_copy(update={"latest_job_id": record["id"]}))
    project = service.update_project(
        project.id, models.ProjectUpdateRequest(
            expected_revision=2,
            scenes=[scene.model_copy(update={"shots": linked})],
        ),
    )
    result = service.assemble_project_master(
        project.id,
        requests.AssembleMasterRequest(expected_revision=project.revision),
    )
    assert result["status"] == "ready"
    assert result["actual_video_probe_verified"] is True
    assert result["timeline_frames"] == 240
    assert result["probe"]["width"] == 3840
    assert result["probe"]["height"] == 2160
    assert result["probe"]["frame_count"] == 240

    master = storage.video_asset_path(result["asset_id"], "mp4")
    with master.open("rb") as handle:
        assert hashlib.file_digest(handle, "sha256").hexdigest() == result["sha256"]
    return master, f"/api/video/assets/{result['asset_id']}.mp4"


def _read_exact_range(path: Path, start: int, length: int) -> bytes:
    with path.open("rb") as handle:
        handle.seek(start)
        return handle.read(length)


def test_actual_4k_master_private_http_range_and_denials(monkeypatch, tmp_path: Path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.fail("Dedicated QA111 requires real FFmpeg and FFprobe")
    master, route = _create_4k_master(monkeypatch, tmp_path)
    size = master.stat().st_size
    assert size > 4096

    # Server import after token setup: real auth middleware and FileResponse.
    for name in ("app.studio.server", "app.video.router"):
        sys.modules.pop(name, None)
    server = importlib.import_module("app.studio.server")
    auth = {"Authorization": f"Bearer {TOKEN}"}

    with TestClient(server.app) as client:
        for headers, params in (
            ({"Range": "bytes=0-1023"}, None),
            ({"Authorization": "Bearer invalid", "Range": "bytes=0-1023"}, None),
            ({"Range": "bytes=-1024"}, {"token": TOKEN}),
        ):
            denied = client.get(route, headers=headers, params=params)
            assert denied.status_code == 401
            assert TOKEN not in denied.text
            assert b"ftyp" not in denied.content
            # QA103/#204 independently confirms that denied 401 currently
            # lacks explicit no-store. Do not conceal or mark it fixed here.

        for requested, start in (
            ("bytes=0-1023", 0),
            (f"bytes={size // 2}-{size // 2 + 1023}", size // 2),
            ("bytes=-1024", size - 1024),
        ):
            response = client.get(route, headers={**auth, "Range": requested})
            assert response.status_code == 206, (requested, response.status_code)
            assert response.headers["content-range"] == (
                f"bytes {start}-{start + 1023}/{size}"
            )
            assert response.headers["content-type"].startswith("video/mp4")
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["content-length"] == "1024"
            assert response.content == _read_exact_range(master, start, 1024)

        invalid = client.get(
            route, headers={**auth, "Range": f"bytes={size}-"},
        )
        assert invalid.status_code == 416
        assert len(invalid.content) < 4096

    # No physical mobile playback, WAN/tunnel test, or 600s 4K claim.
