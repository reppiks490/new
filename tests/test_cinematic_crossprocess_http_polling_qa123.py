"""QA123: authenticated mobile-style polling across a real SQLite worker process.

Real FastAPI/TestClient HTTP, SQLite WAL, and independent Python interpreter.
The project lookup and assembly result are synthetic; no FFmpeg, model inference,
owner media, actual mobile device, cloud generation, or production code edits.
"""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient

from app.studio.storage import connection

_PROJECT = "a" * 32
_OTHER_PROJECT = "b" * 32
_TOKEN = "QA123_DISPOSABLE_LOCAL_TEST_TOKEN"
_PRIVATE = "QA123_PRIVATE_SCREENPLAY_SENTINEL_NEVER_PUBLIC"

_CHILD = r"""
import json
from pathlib import Path
import sys
import time
from app.video import cinematic_assembly_jobs as queue
from app.video.storage import put_video_record

mode, project_id, job_id, ready_path, release_path = sys.argv[1:]
claimed = queue._claim_next()
assert claimed is not None and claimed["id"] == job_id
assert claimed["project_id"] == project_id
Path(ready_path).write_text("claimed", encoding="utf-8")
deadline = time.monotonic() + 30
while not Path(release_path).exists():
    if time.monotonic() > deadline:
        raise TimeoutError("QA123 worker release gate timed out")
    time.sleep(0.01)

def synthetic_assemble(project_id, request):
    assert project_id == claimed["project_id"]
    assert request.expected_revision == claimed["project_revision"]
    if mode == "failure":
        raise RuntimeError("QA123_PRIVATE_SCREENPLAY_SENTINEL_NEVER_PUBLIC")
    asset_id = "d" * 32
    return put_video_record("video_master", {
        "project_id": project_id,
        "project_revision": request.expected_revision,
        "asset_id": asset_id,
        "asset_url": f"/api/video/assets/{asset_id}.mp4",
        "status": "ready",
        "actual_video_probe_verified": True,
        "probe": {"probe_metadata_verified": True},
        "sha256": "e" * 64,
    }, identifier="c" * 32)

queue.assemble_project_master = synthetic_assemble
queue._execute_one(claimed)
result = queue.get_master_assembly_job(project_id, job_id)
print(json.dumps({"status": result["status"]}), flush=True)
"""


def _seed(monkeypatch, workspace: Path, identifier: str) -> None:
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(workspace))
    monkeypatch.setenv("CHARACTER3D_STUDIO_TOKEN", _TOKEN)
    payload = {
        "project_id": _PROJECT,
        "project_revision": 3,
        "ffmpeg_path": "ffmpeg",
        "status": "queued",
        "stage": "Queued",
        "progress": 0,
        "created_at": 100.0,
        "updated_at": 100.0,
    }
    with connection() as db:
        db.execute(
            "INSERT INTO records(id,kind,data,updated) VALUES(?,?,?,?)",
            (identifier, "video_assembly_job", json.dumps(payload), 100.0),
        )


def _get(client: TestClient, identifier: str, headers: dict[str, str]):
    return client.get(
        f"/api/video/projects/{_PROJECT}/assembly-jobs/{identifier}",
        headers=headers,
    )


@pytest.mark.parametrize("mode", ["success", "failure"])
def test_private_mobile_polling_observes_separate_worker_process_and_reconnect(
    monkeypatch, tmp_path: Path, mode: str,
):
    workspace = tmp_path / mode
    identifier = "1" * 32 if mode == "success" else "2" * 32
    _seed(monkeypatch, workspace, identifier)

    # Stub ONLY unrelated project existence. Real auth, router, queue, and
    # SQLite record reads are used; no startup lifespan/recovery is invoked.
    video_router = importlib.import_module("app.video.router")
    monkeypatch.setattr(video_router, "get_project", lambda project_id: object())
    server = importlib.import_module("app.studio.server")
    client = TestClient(server.app)
    auth = {"Authorization": f"Bearer {_TOKEN}"}
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(root), env.get("PYTHONPATH", "")) if part
    )
    ready, release = workspace / "claimed", workspace / "finish"
    child = None
    try:
        initial = _get(client, identifier, auth)
        assert initial.status_code == 200
        assert initial.json()["status"] == "queued"
        assert _PRIVATE not in initial.text

        for headers in ({}, {"Authorization": "Bearer invalid"}):
            denied = _get(client, identifier, headers)
            assert denied.status_code == 401
            assert _PRIVATE not in denied.text
        assert client.get(
            f"/api/video/projects/{_PROJECT}/assembly-jobs/{identifier}?token={_TOKEN}"
        ).status_code == 401
        assert client.get(
            f"/api/video/projects/{_OTHER_PROJECT}/assembly-jobs/{identifier}",
            headers=auth,
        ).status_code == 404

        child = subprocess.Popen(
            [sys.executable, "-u", "-c", _CHILD, mode, _PROJECT,
             identifier, str(ready), str(release)],
            cwd=root, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True,
        )
        deadline = time.monotonic() + 30
        while not ready.exists():
            assert child.poll() is None, "Synthetic worker exited before claim"
            assert time.monotonic() < deadline, "QA123 claim gate timed out"
            time.sleep(0.02)

        running = _get(client, identifier, auth)
        assert running.status_code == 200
        assert running.json()["status"] == "running"
        assert running.json()["started_at"] >= initial.json()["updated_at"]
        assert running.json()["progress"] is None
        assert "master_id" not in running.json()

        page = client.get(
            f"/api/video/projects/{_PROJECT}/assembly-jobs",
            params={"limit": 1, "offset": 0}, headers=auth,
        )
        assert page.status_code == 200
        assert page.json()["total"] == 1
        assert page.json()["has_more"] is False
        assert page.json()["jobs"][0]["status"] == "running"

        release.write_text("go", encoding="utf-8")
        stdout, stderr = child.communicate(timeout=30)
        assert child.returncode == 0, f"QA123 worker failed: {stderr[-1000:]}"
        assert _PRIVATE not in stdout + stderr
        assert json.loads(stdout.strip())["status"] == (
            "succeeded" if mode == "success" else "failed"
        )

        # A fresh HTTP client models reconnect, not a physical mobile device.
        reconnect = TestClient(server.app)
        try:
            final = _get(reconnect, identifier, auth)
            assert final.status_code == 200
            body = final.json()
            assert body["id"] == identifier
            assert body["status"] == (
                "succeeded" if mode == "success" else "failed"
            )
            assert body["finished_at"] >= running.json()["started_at"]
            assert body["updated_at"] >= running.json()["updated_at"]
            assert _PRIVATE not in final.text
            if mode == "success":
                assert body["master_id"] == "c" * 32
                assert body["asset_id"] == "d" * 32
                assert body["sha256"] == "e" * 64
                assert body["probe_metadata_verified"] is True
                assert body["progress"] == 100
            else:
                assert body["stage"] == "Assembly failed"
                assert body["error"] == (
                    "Local master assembly failed. Inspect the private worker diagnostics."
                )
                assert "asset_id" not in body
                assert "sha256" not in body

            history = reconnect.get(
                f"/api/video/projects/{_PROJECT}/assembly-jobs",
                params={"limit": 1, "offset": 0}, headers=auth,
            )
            assert history.status_code == 200
            assert history.json()["total"] == 1
            assert history.json()["has_more"] is False
            assert history.json()["jobs"][0]["status"] == body["status"]
            assert history.json()["jobs"][0]["id"] == identifier
            assert _PRIVATE not in history.text
        finally:
            reconnect.close()
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            child.communicate(timeout=10)
        client.close()
