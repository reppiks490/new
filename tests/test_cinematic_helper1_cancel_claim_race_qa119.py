"""QA119: HTTP cancellation and worker claim cannot both win a SQLite race.

Real FastAPI TestClient + disposable SQLite WAL and two simultaneous threads.
The worker pool and project readiness are synthetic: no FFmpeg or private media.
"""
from __future__ import annotations

import importlib
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

_TOKEN = "qa119-local-only-secret"
_PRIVATE = "QA119_PRIVATE_SCREENPLAY_MUST_NOT_LEAK"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


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
    first = service.create_project(models.ProjectCreateRequest(
        title="Synthetic private QA119 project",
        master_prompt=_PRIVATE,
        target_duration_seconds=10,
        delivery_fps=24,
        delivery_resolution="480p",
        aspect_ratio="16:9",
    ))
    other = service.create_project(models.ProjectCreateRequest(
        title="Synthetic foreign QA119 project",
        master_prompt="QA119_FOREIGN_PRIVATE",
        target_duration_seconds=10,
        delivery_fps=24,
        delivery_resolution="480p",
        aspect_ratio="16:9",
    ))
    for name in ("app.studio.server", "app.video.router"):
        sys.modules.pop(name, None)
    app = importlib.import_module("app.studio.server").app
    return app, queue, first, other


def _enqueue(client, project):
    response = client.post(
        f"/api/video/projects/{project.id}/assembly-jobs",
        headers=_AUTH, json={"expected_revision": project.revision},
    )
    assert response.status_code == 202, response.text
    return response.json()


def _cancel(client, project_id, job_id):
    return client.post(
        f"/api/video/projects/{project_id}/assembly-jobs/{job_id}/cancel",
        headers=_AUTH,
    )


def _no_private(response):
    assert _TOKEN not in response.text
    assert _PRIVATE not in response.text
    assert "QA119_FOREIGN_PRIVATE" not in response.text


def test_http_cancel_and_worker_claim_are_mutually_exclusive(monkeypatch, tmp_path):
    app, queue, project, _ = _setup(monkeypatch, tmp_path)
    with TestClient(app) as client:
        for _ in range(8):
            job = _enqueue(client, project)
            gate = Barrier(2)

            def claim():
                gate.wait(timeout=10)
                return queue._claim_next()

            def cancel():
                gate.wait(timeout=10)
                return _cancel(client, project.id, job["id"])

            with ThreadPoolExecutor(max_workers=2) as pool:
                claimed_future = pool.submit(claim)
                cancelled_future = pool.submit(cancel)
                claimed = claimed_future.result(timeout=15)
                response = cancelled_future.result(timeout=15)

            _no_private(response)
            state = queue.get_master_assembly_job(project.id, job["id"])
            if response.status_code == 200:
                assert claimed is None
                assert state["status"] == "cancelled"
                assert response.json()["status"] == "cancelled"
            else:
                assert response.status_code == 409, response.text
                assert claimed is not None and claimed["id"] == job["id"]
                assert state["status"] == "running"
                # Synthetic cleanup, not a real completed master.
                assert queue._store_status(job["id"], status="failed", stage="QA cleanup")


@pytest.mark.parametrize("terminal", ["running", "failed", "succeeded"])
def test_http_cancel_refuses_claimed_or_terminal_work_without_mutation(
    monkeypatch, tmp_path, terminal,
):
    app, queue, project, foreign = _setup(monkeypatch, tmp_path)
    with TestClient(app) as client:
        job = _enqueue(client, project)
        claimed = queue._claim_next()
        assert claimed is not None and claimed["id"] == job["id"]
        if terminal != "running":
            assert queue._store_status(
                job["id"], status=terminal, stage="QA synthetic terminal",
            )
        before = queue.get_master_assembly_job(project.id, job["id"])
        foreign_response = _cancel(client, foreign.id, job["id"])
        own_response = _cancel(client, project.id, job["id"])
        assert foreign_response.status_code == 404
        assert own_response.status_code == 409
        for response in (foreign_response, own_response):
            _no_private(response)
        assert queue.get_master_assembly_job(project.id, job["id"]) == before
