"""QA102: authenticated HTTP byte ranges on a genuine 600s Character3D master.

This tests the private API response, not physical mobile playback. The master
is assembled from locally generated synthetic FFmpeg color clips; no owner
media, model inference, external services, or network access are involved.
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient


pytestmark = pytest.mark.skipif(
    os.environ.get("CINEMATIC_600S_HTTP_RANGE_QA") != "1",
    reason="600-second real-media private HTTP Range QA is opt-in",
)
TOKEN = "qa102-synthetic-local-owner-token"


def _run(args: list[str], timeout: int = 600) -> None:
    subprocess.run(args, check=True, capture_output=True, timeout=timeout)


def _master(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("CHARACTER3D_STUDIO_TOKEN", TOKEN)
    monkeypatch.setenv("CHARACTER3D_STUDIO_ORIGINS", "")
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    storage = importlib.import_module("app.video.storage")
    requests = importlib.import_module("app.video.cinematic_requests")

    asset_ids = []
    for index, color in enumerate(("red", "blue")):
        asset_id = f"{3100 + index:032x}"
        path = storage.video_asset_path(asset_id, "mp4")
        _run([
            "ffmpeg", "-nostdin", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=160x90:r=24:d=1",
            "-an", "-c:v", "mpeg4", "-q:v", "4", str(path),
        ], timeout=90)
        asset_ids.append(asset_id)

    project = service.create_project(models.ProjectCreateRequest(
        title="QA102 synthetic 600-second authenticated Range film",
        master_prompt="Synthetic colors only; no private script or model inference.",
        target_duration_seconds=600, delivery_fps=24,
        delivery_resolution="480p", aspect_ratio="16:9",
    ))
    shots = [
        models.CinematicShot(
            shot_id=f"{3200 + i:032x}", ordinal=i + 1,
            title=f"QA102 shot {i + 1}", prompt="Synthetic color only",
            duration_seconds=30,
        )
        for i in range(20)
    ]
    scene = models.CinematicScene(
        scene_id="9" * 32, ordinal=1, title="Range seek timeline",
        target_duration_seconds=600, shots=shots,
    )
    project = service.update_project(
        project.id,
        models.ProjectUpdateRequest(expected_revision=1, scenes=[scene]),
    )
    linked = []
    for i, shot in enumerate(project.scenes[0].shots):
        asset_id = asset_ids[0 if i < 10 else 1]
        job = storage.put_video_record("video_job", {
            "status": "succeeded", "project_id": project.id,
            "scene_id": scene.scene_id, "shot_id": shot.shot_id,
            "project_revision": project.revision, "asset_id": asset_id,
            "asset_url": f"/api/video/assets/{asset_id}.mp4",
        })
        linked.append(shot.model_copy(update={"latest_job_id": job["id"]}))
    project = service.update_project(
        project.id,
        models.ProjectUpdateRequest(
            expected_revision=2,
            scenes=[scene.model_copy(update={"shots": linked})],
        ),
    )
    result = service.assemble_project_master(
        project.id, requests.AssembleMasterRequest(expected_revision=project.revision),
    )
    assert result["status"] == "ready"
    assert result["timeline_frames"] == 14_400
    assert result["probe"]["frame_count"] == 14_400
    path = storage.video_asset_path(result["asset_id"], "mp4")
    assert path.is_file()
    return path, f"/api/video/assets/{result['asset_id']}.mp4"


def _expected_range(path: Path, start: int, length: int) -> bytes:
    with path.open("rb") as handle:
        handle.seek(start)
        return handle.read(length)


def test_600s_assembled_master_authenticated_http_ranges(monkeypatch, tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.fail("Opt-in genuine-media QA requires FFmpeg and FFprobe")
    master, route = _master(monkeypatch, tmp_path)
    size = master.stat().st_size
    assert size > 4096

    # Import server after setting the bearer token. TestClient exercises the
    # actual middleware + FileResponse, not a mocked Range implementation.
    for name in ("app.studio.server", "app.video.router"):
        sys.modules.pop(name, None)
    server = importlib.import_module("app.studio.server")
    auth = {"Authorization": f"Bearer {TOKEN}"}

    with TestClient(server.app) as client:
        for headers, params in (
            ({"Range": "bytes=0-1023"}, None),
            ({"Authorization": "Bearer incorrect", "Range": "bytes=0-1023"}, None),
            ({"Range": "bytes=-1024"}, {"token": TOKEN}),
        ):
            denied = client.get(route, headers=headers, params=params)
            assert denied.status_code == 401
            assert TOKEN not in denied.text
            assert denied.headers.get("cache-control", "no-store") == "no-store"

        # A player must be able to request the MP4 header, an interior range
        # (e.g. after a seek), and the tail without fetching the whole film.
        for header, start, end in (
            ("bytes=0-1023", 0, 1023),
            (f"bytes={size // 2}-{size // 2 + 1023}", size // 2, size // 2 + 1023),
            ("bytes=-1024", size - 1024, size - 1),
        ):
            response = client.get(route, headers={**auth, "Range": header})
            assert response.status_code == 206, (header, response.status_code)
            assert response.headers["content-range"] == f"bytes {start}-{end}/{size}"
            assert response.headers["content-type"].startswith("video/mp4")
            assert response.headers["cache-control"] == "no-store"
            expected = _expected_range(master, start, 1024)
            if response.content != expected:
                mismatch = next((i for i, (a, b) in enumerate(zip(response.content, expected)) if a != b), None)
                pytest.fail(
                    f"Range {header} body mismatch at byte {mismatch}; "
                    f"received={len(response.content)} expected={len(expected)}; "
                    f"head={response.content[:12].hex()} vs {expected[:12].hex()}"
                )
            assert len(response.content) == 1024

    # This is in-process authenticated HTTP acceptance, not an iOS/Android
    # device, remote tunnel, CDN, browser media element, or Windows test.
