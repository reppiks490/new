"""QA124: genuine synthetic FFmpeg master through an independent SQLite worker.

Exercises the real Character3D queue claim, master assembly, private HTTP
polling, and Range delivery across a process boundary. Only the CPU executor
submission is held so the test can explicitly release the separate worker.
No model inference, owner media, physical phone, or multi-API-server claim.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from fractions import Fraction

import pytest
from fastapi.testclient import TestClient


pytestmark = pytest.mark.skipif(
    os.environ.get("CINEMATIC_CROSSPROCESS_REALMEDIA_QA124") != "1",
    reason="opt-in independent-process genuine synthetic FFmpeg acceptance",
)
_TOKEN = "QA124_DISPOSABLE_SYNTHETIC_TEST_TOKEN"
_PRIVATE = "QA124_PRIVATE_SCRIPT_SENTINEL_NEVER_PUBLIC"
_CHILD = r"""
import json
from pathlib import Path
import sys
import time
from app.video import cinematic_assembly_jobs as queue

project_id, job_id, ready_path, release_path = sys.argv[1:]
claimed = queue._claim_next()
assert claimed is not None and claimed["id"] == job_id
assert claimed["project_id"] == project_id
Path(ready_path).write_text("claimed", encoding="utf-8")
deadline = time.monotonic() + 45
while not Path(release_path).exists():
    if time.monotonic() > deadline:
        raise TimeoutError("QA124 worker release gate expired")
    time.sleep(0.02)
# The real queue callback invokes real FFmpeg/FFprobe and persists the master.
queue._execute_one(claimed)
job = queue.get_master_assembly_job(project_id, job_id)
print(json.dumps({"status": job["status"]}), flush=True)
"""


class HeldExecutor:
    def __init__(self):
        self.tasks = []

    def submit(self, fn, *args, **kwargs):
        self.tasks.append((fn, args, kwargs))
        return object()


def _run(args: list[str], timeout: int = 180):
    return subprocess.run(args, check=True, capture_output=True, timeout=timeout)


def _setup_project(monkeypatch, workspace: Path, ffmpeg: str):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(workspace))
    monkeypatch.setenv("CHARACTER3D_STUDIO_TOKEN", _TOKEN)
    monkeypatch.setenv("CHARACTER3D_STUDIO_ORIGINS", "")
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    storage = importlib.import_module("app.video.storage")
    queue = importlib.import_module("app.video.cinematic_assembly_jobs")
    held = HeldExecutor()
    monkeypatch.setattr(queue, "assembly_pool", held)

    project = service.create_project(models.ProjectCreateRequest(
        title="QA124 offline independent-process FFmpeg acceptance",
        master_prompt=_PRIVATE,
        target_duration_seconds=10,
        delivery_fps=24,
        delivery_resolution="480p",
        aspect_ratio="16:9",
    ))
    shots = [
        models.CinematicShot(
            shot_id=f"{index + 140:032x}", ordinal=index + 1,
            title=f"Synthetic color {index + 1}",
            prompt="Disposable FFmpeg color, no inference",
            duration_seconds=5,
        )
        for index in range(2)
    ]
    scene = models.CinematicScene(
        scene_id="a" * 32, ordinal=1, title="Offline synthetic reel",
        target_duration_seconds=10, shots=shots,
    )
    project = service.update_project(
        project.id,
        models.ProjectUpdateRequest(expected_revision=1, scenes=[scene]),
    )
    linked = []
    for index, (color, fps) in enumerate((("red", 24), ("blue", 30))):
        asset_id = f"{index + 150:032x}"
        path = storage.video_asset_path(asset_id, "mp4")
        _run([
            ffmpeg, "-nostdin", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=160x90:r={fps}:d=5",
            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(path),
        ])
        assert path.is_file() and path.stat().st_size > 128
        record = storage.put_video_record("video_job", {
            "status": "succeeded", "project_id": project.id,
            "scene_id": scene.scene_id, "shot_id": shots[index].shot_id,
            "project_revision": project.revision, "asset_id": asset_id,
            "asset_url": f"/api/video/assets/{asset_id}.mp4",
        })
        linked.append(shots[index].model_copy(update={
            "latest_job_id": record["id"],
            "latest_rendered_project_revision": 2,
        }))
    project = service.update_project(
        project.id, models.ProjectUpdateRequest(
            expected_revision=2, scenes=[scene.model_copy(update={"shots": linked})],
        ),
    )
    assert project.revision == 3
    assert service.project_render_status(project.id)["ready_for_assembly"]
    return project, held, storage


def test_independent_sqlite_worker_produces_real_decodable_private_http_master(
    monkeypatch, tmp_path: Path,
):
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    assert ffmpeg and ffprobe, "QA124 dedicated acceptance requires FFmpeg and FFprobe"
    project, held, storage = _setup_project(monkeypatch, tmp_path, ffmpeg)

    # Re-import HTTP after setting disposable auth; hold startup/POST dispatch.
    for name in ("app.studio.server", "app.video.router"):
        sys.modules.pop(name, None)
    server = importlib.import_module("app.studio.server")
    auth = {"Authorization": f"Bearer {_TOKEN}"}
    base = f"/api/video/projects/{project.id}/assembly-jobs"
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(root), env.get("PYTHONPATH", "")) if part
    )
    ready, release = tmp_path / "worker-claimed", tmp_path / "worker-release"
    child = None
    try:
        with TestClient(server.app) as client:
            denied = client.post(base, json={"expected_revision": project.revision})
            assert denied.status_code == 401
            assert _PRIVATE not in denied.text
            submitted = client.post(
                base, json={"expected_revision": project.revision}, headers=auth,
            )
            assert submitted.status_code == 202, submitted.text
            queued = submitted.json()
            assert queued["status"] == "queued"
            assert held.tasks, "API dispatch should be held, not silently executed"
            detail = f"{base}/{queued['id']}"
            assert client.get(detail, headers=auth).json()["status"] == "queued"

            child = subprocess.Popen(
                [sys.executable, "-u", "-c", _CHILD, project.id, queued["id"],
                 str(ready), str(release)],
                cwd=root, env=env, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True,
            )
            deadline = time.monotonic() + 45
            while not ready.exists():
                assert child.poll() is None, "Worker exited before claiming queue job"
                assert time.monotonic() < deadline, "Worker claim timed out"
                time.sleep(0.02)
            running = client.get(detail, headers=auth)
            assert running.status_code == 200
            assert running.json()["status"] == "running"
            assert "master_id" not in running.json()
            assert running.json()["progress"] is None
            assert client.get(detail).status_code == 401

            release.write_text("go", encoding="utf-8")
            stdout, stderr = child.communicate(timeout=180)
            assert child.returncode == 0, f"QA124 worker failed: {stderr[-1200:]}"
            assert _PRIVATE not in stdout + stderr
            assert json.loads(stdout.strip())["status"] == "succeeded", (
                "Real FFmpeg assembly did not succeed"
            )

            # Reconnect uses a new in-process HTTP client, not a physical phone.
            with TestClient(server.app) as reconnect:
                final = reconnect.get(detail, headers=auth)
                assert final.status_code == 200
                body = final.json()
                assert body["status"] == "succeeded", body
                assert body["finished_at"] >= running.json()["started_at"]
                assert body["probe_metadata_verified"] is True
                assert body["progress"] == 100
                assert _PRIVATE not in final.text
                route = body["asset_url"]
                assert route == f"/api/video/assets/{body['asset_id']}.mp4"
                assert reconnect.get(route).status_code == 401
                assert reconnect.get(route, params={"token": _TOKEN}).status_code == 401
                media = reconnect.get(route, headers=auth)
                assert media.status_code == 200
                assert media.headers["cache-control"] == "no-store"
                assert media.headers["content-type"].startswith("video/mp4")
                assert hashlib.sha256(media.content).hexdigest() == body["sha256"]
                assert b"ftyp" in media.content[:12]
                size = len(media.content)
                assert size > 4096
                part = reconnect.get(
                    route, headers={**auth, "Range": "bytes=0-1023"},
                )
                assert part.status_code == 206
                assert part.headers["content-range"] == f"bytes 0-1023/{size}"
                assert part.headers["cache-control"] == "no-store"
                assert part.content == media.content[:1024]
                history = reconnect.get(
                    base, params={"limit": 1, "offset": 0}, headers=auth,
                )
                assert history.status_code == 200
                assert history.json()["total"] == 1
                assert history.json()["jobs"][0]["status"] == "succeeded"
                assert _PRIVATE not in history.text

        master = storage.video_asset_path(body["asset_id"], "mp4")
        assert master.is_file()
        assert master.read_bytes() == media.content
        metadata = json.loads(_run([
            ffprobe, "-v", "error", "-show_streams", "-show_format",
            "-of", "json", str(master),
        ]).stdout)
        videos = [s for s in metadata["streams"] if s["codec_type"] == "video"]
        assert len(videos) == 1
        stream = videos[0]
        assert stream["codec_name"] == "h264"
        assert (stream["width"], stream["height"]) == (854, 480)
        assert Fraction(stream["avg_frame_rate"]) == Fraction(24, 1)
        assert int(stream["nb_frames"]) == 240
        assert float(metadata["format"]["duration"]) == pytest.approx(10, abs=0.25)
        _run([ffmpeg, "-nostdin", "-v", "error", "-xerror",
              "-i", str(master), "-an", "-f", "null", "-"])
        for seconds, channel in ((1, 0), (7, 2)):
            sample = _run([
                ffmpeg, "-nostdin", "-v", "error", "-ss", str(seconds),
                "-i", str(master), "-frames:v", "1", "-vf", "scale=1:1",
                "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
            ]).stdout
            assert len(sample) == 3
            assert sample[channel] > 100
            assert sample[channel] > sample[2 if channel == 0 else 0] + 60
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            child.communicate(timeout=10)
