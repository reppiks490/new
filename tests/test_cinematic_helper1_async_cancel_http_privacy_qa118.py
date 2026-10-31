"""Helper 1 QA118: authenticated async cancellation is project-scoped and side-effect-free on denial.

Actual FastAPI TestClient + disposable SQLite; project readiness and executor are
stubbed. No FFmpeg, owner footage, credentials, paid generation or live workers.
This complements QA117's direct cross-process cancellation test by covering HTTP.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient

_TOKEN = "qa118-local-test-secret"
_PRIVATE = "QA118_PRIVATE_SCREENPLAY_NEVER_RETURN"
_OTHER_PRIVATE = "QA118_OTHER_PROJECT_PRIVATE"
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

    # Deliberately isolate the cancellation HTTP contract from FFmpeg/readiness.
    monkeypatch.setattr(queue, "assembly_pool", _HoldingPool())
    monkeypatch.setattr(queue, "enforce_film_duration", lambda project: None)
    monkeypatch.setattr(
        queue, "project_render_status",
        lambda identifier: {"ready_for_assembly": True},
    )

    def project(marker: str):
        return service.create_project(models.ProjectCreateRequest(
            title="Private cinematic QA project",
            master_prompt=f"{marker}: confidential cinematic scene",
            target_duration_seconds=10,
            delivery_fps=24,
            delivery_resolution="480p",
            aspect_ratio="16:9",
        ))

    first, second = project(_PRIVATE), project(_OTHER_PRIVATE)
    for name in ("app.studio.server", "app.video.router"):
        sys.modules.pop(name, None)
    server = importlib.import_module("app.studio.server")
    return server.app, queue, first, second


def _enqueue(client: TestClient, project_id: str, revision: int) -> dict:
    response = client.post(
        f"/api/video/projects/{project_id}/assembly-jobs",
        headers=_AUTH, json={"expected_revision": revision},
    )
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "queued"
    return response.json()


def _assert_private_response(response):
    for marker in (_PRIVATE, _OTHER_PRIVATE, _TOKEN):
        assert marker not in response.text


def test_cancel_http_denials_cannot_mutate_queued_job(monkeypatch, tmp_path: Path):
    app, queue, first, _ = _setup(monkeypatch, tmp_path)
    with TestClient(app) as client:
        job = _enqueue(client, first.id, first.revision)
        path = f"/api/video/projects/{first.id}/assembly-jobs/{job['id']}/cancel"
        rejected = (
            client.post(path),
            client.post(path, headers={"Authorization": "Bearer wrong"}),
            client.post(path, params={"token": _TOKEN}),
            client.post(path, headers={**_AUTH, "Origin": "https://foreign.invalid"}),
        )
        assert [r.status_code for r in rejected] == [401, 401, 401, 403]
        for response in rejected:
            _assert_private_response(response)
            assert queue.get_master_assembly_job(first.id, job["id"])["status"] == "queued"

        first_cancel = client.post(path, headers=_AUTH)
        repeat_cancel = client.post(path, headers=_AUTH)
        assert first_cancel.status_code == repeat_cancel.status_code == 200
        for response in (first_cancel, repeat_cancel):
            _assert_private_response(response)
            assert response.json()["id"] == job["id"]
            assert response.json()["status"] == "cancelled"
        assert queue.get_master_assembly_job(first.id, job["id"])["status"] == "cancelled"


def test_cancel_http_foreign_project_cannot_touch_private_job(monkeypatch, tmp_path: Path):
    app, queue, first, other = _setup(monkeypatch, tmp_path)
    with TestClient(app) as client:
        job = _enqueue(client, first.id, first.revision)
        foreign = client.post(
            f"/api/video/projects/{other.id}/assembly-jobs/{job['id']}/cancel",
            headers=_AUTH,
        )
        assert foreign.status_code == 404, foreign.text
        _assert_private_response(foreign)
        assert queue.get_master_assembly_job(first.id, job["id"])["status"] == "queued"
        assert queue.list_master_assembly_jobs(other.id)["total"] == 0

        own = client.get(
            f"/api/video/projects/{first.id}/assembly-jobs/{job['id']}",
            headers=_AUTH,
        )
        assert own.status_code == 200, own.text
        assert own.json()["status"] == "queued"
        _assert_private_response(own)
