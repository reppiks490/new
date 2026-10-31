"""QA122: authenticated HTTP cancellation versus a separate process's SQLite claim.

Real FastAPI HTTP, a separate Python interpreter, and disposable SQLite WAL.
The executor and render readiness are simulated; no FFmpeg or owner media.
"""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from fastapi.testclient import TestClient

_TOKEN = "qa122-local-test-token"
_PRIVATE = "QA122_PRIVATE_SCREENPLAY_NOT_FOR_RESPONSE"
_FOREIGN = "QA122_OTHER_PRIVATE_NOT_FOR_RESPONSE"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}

_CLAIM_CHILD = r"""
import json
import os
from pathlib import Path
import sys
import time
from app.video import cinematic_assembly_jobs as queue

ready, go = map(Path, sys.argv[1:])
ready.write_text(str(os.getpid()), encoding="utf-8")
deadline = time.monotonic() + 25
while not go.exists():
    if time.monotonic() > deadline:
        raise TimeoutError("QA122 claim gate timed out")
    time.sleep(0.005)
claimed = queue._claim_next()
print(json.dumps({"pid": os.getpid(), "id": claimed["id"] if claimed else None}), flush=True)
"""


class _HoldingPool:
    def submit(self, fn, *args, **kwargs):
        return object()


def _setup(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("CHARACTER3D_STUDIO_TOKEN", _TOKEN)
    monkeypatch.setenv("CHARACTER3D_STUDIO_ORIGINS", "")
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    queue = importlib.import_module("app.video.cinematic_assembly_jobs")
    monkeypatch.setattr(queue, "assembly_pool", _HoldingPool())
    monkeypatch.setattr(queue, "enforce_film_duration", lambda project: None)
    monkeypatch.setattr(
        queue, "project_render_status",
        lambda identifier: {"ready_for_assembly": True},
    )

    def project(marker):
        return service.create_project(models.ProjectCreateRequest(
            title="Synthetic QA122 project",
            master_prompt=marker,
            target_duration_seconds=10,
            delivery_fps=24,
            delivery_resolution="480p",
            aspect_ratio="16:9",
        ))

    own, foreign = project(_PRIVATE), project(_FOREIGN)
    for module in ("app.studio.server", "app.video.router"):
        sys.modules.pop(module, None)
    app = importlib.import_module("app.studio.server").app
    return app, queue, own, foreign


def _assert_no_private(response):
    for secret in (_TOKEN, _PRIVATE, _FOREIGN):
        assert secret not in response.text


def test_http_cancel_races_independent_process_claim_without_cross_project_leak(
    monkeypatch, tmp_path: Path,
):
    app, queue, own, foreign = _setup(monkeypatch, tmp_path)
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        item for item in (str(root), env.get("PYTHONPATH", "")) if item
    )
    with TestClient(app) as client:
        for round_index in range(8):
            created = client.post(
                f"/api/video/projects/{own.id}/assembly-jobs",
                headers=_AUTH,
                json={"expected_revision": own.revision},
            )
            assert created.status_code == 202, created.text
            job_id = created.json()["id"]
            cancel_path = (
                f"/api/video/projects/{own.id}/assembly-jobs/{job_id}/cancel"
            )
            foreign_response = client.post(
                f"/api/video/projects/{foreign.id}/assembly-jobs/{job_id}/cancel",
                headers=_AUTH,
            )
            assert foreign_response.status_code == 404
            _assert_no_private(foreign_response)
            assert queue.get_master_assembly_job(own.id, job_id)["status"] == "queued"

            gate = tmp_path / f"gate-{round_index}"
            gate.mkdir()
            ready, go = gate / "child.ready", gate / "go"
            proc = subprocess.Popen(
                [sys.executable, "-u", "-c", _CLAIM_CHILD, str(ready), str(go)],
                cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True,
            )
            http_ready = Event()

            def http_cancel():
                http_ready.set()
                deadline = time.monotonic() + 25
                while not go.exists():
                    if time.monotonic() > deadline:
                        raise TimeoutError("QA122 HTTP gate timed out")
                    time.sleep(0.005)
                return client.post(cancel_path, headers=_AUTH)

            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(http_cancel)
                    deadline = time.monotonic() + 30
                    while not (ready.exists() and http_ready.is_set()):
                        assert time.monotonic() < deadline, "QA122 readiness timed out"
                        assert proc.poll() is None, "QA122 child exited before gate"
                        time.sleep(0.01)
                    go.write_text("go", encoding="utf-8")
                    response = future.result(timeout=30)
                stdout, stderr = proc.communicate(timeout=35)
                assert proc.returncode == 0, stderr[-1000:]
                assert _PRIVATE not in stdout + stderr
                assert _FOREIGN not in stdout + stderr
                assert _TOKEN not in stdout + stderr
                claim = json.loads(stdout.strip())
                assert claim["pid"] != os.getpid()
                _assert_no_private(response)
                durable = queue.get_master_assembly_job(own.id, job_id)
                if response.status_code == 200:
                    assert response.json()["status"] == "cancelled"
                    assert claim["id"] is None
                    assert durable["status"] == "cancelled"
                    assert queue._claim_next() is None
                    again = client.post(cancel_path, headers=_AUTH)
                    assert again.status_code == 200
                    _assert_no_private(again)
                else:
                    assert response.status_code == 409, response.text
                    assert claim["id"] == job_id
                    assert durable["status"] == "running"
                    assert queue._store_status(
                        job_id, status="failed", stage="QA122 synthetic cleanup",
                        progress=0, error=None,
                    )["status"] == "failed"
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.communicate(timeout=10)
