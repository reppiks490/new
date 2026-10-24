"""QA41: a committed cinematic master job must not lose its receipt on worker-submit failure.

Real temporary SQLite project/queue, held/rejecting executor, authenticated FastAPI.
Synthetic MP4 signature only: NO FFmpeg, model inference, owner footage, or phone.
The strict API contract is intentionally opt-in until a lead-owned fix exists.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

STRICT = os.getenv("CINEMATIC_REQUIRE_ASSEMBLY_DISPATCH_RECEIPT_QA41") == "1"
SCENE_ID = "2" * 32
SHOT_ID = "3" * 32
PRIVATE_SENTINEL = "PRIVATE_QA41_SCREENPLAY_MUST_NOT_LEAK"


class HoldingPool:
    def __init__(self):
        self.submissions = []

    def submit(self, fn, *args, **kwargs):
        self.submissions.append((fn, args, kwargs))
        return object()


class RejectingPool:
    def submit(self, fn, *args, **kwargs):
        raise RuntimeError("synthetic executor shutdown")


@pytest.fixture
def ready_project(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    storage = importlib.import_module("app.video.storage")
    queue = importlib.import_module("app.video.cinematic_assembly_jobs")
    requests = importlib.import_module("app.video.cinematic_requests")

    project = service.create_project(models.ProjectCreateRequest(
        title="Synthetic queue dispatch QA41",
        master_prompt=PRIVATE_SENTINEL,
        target_duration_seconds=10,
        delivery_fps=24,
        delivery_resolution="480p",
        aspect_ratio="16:9",
    ))
    shot = models.CinematicShot(
        shot_id=SHOT_ID, ordinal=1, title="Shot", prompt="Synthetic camera pan",
        duration_seconds=2,
    )
    scene = models.CinematicScene(
        scene_id=SCENE_ID, ordinal=1, title="Scene",
        target_duration_seconds=2, shots=[shot],
    )
    project = service.update_project(
        project.id, models.ProjectUpdateRequest(expected_revision=1, scenes=[scene]),
    )
    asset_id = "4" * 32
    # This is only the existing queue's signature-level readiness fixture.
    # It is deliberately NOT a real, decodable MP4 or an FFmpeg test.
    storage.video_asset_path(asset_id, "mp4").write_bytes(
        b"\\x00\\x00\\x00\\x18ftypmp42synthetic"
    )
    record = storage.put_video_record("video_job", {
        "status": "succeeded", "project_id": project.id,
        "scene_id": SCENE_ID, "shot_id": SHOT_ID,
        "asset_id": asset_id, "project_revision": 2,
    })
    shot = shot.model_copy(update={"latest_job_id": record["id"]})
    project = service.update_project(
        project.id,
        models.ProjectUpdateRequest(
            expected_revision=2,
            scenes=[scene.model_copy(update={"shots": [shot]})],
        ),
    )
    assert service.project_render_status(project.id)["ready_for_assembly"]
    return service, queue, requests, project


def test_rejected_dispatch_preserves_one_durable_job_and_idempotent_retry(
    monkeypatch, ready_project,
):
    _, queue, requests, project = ready_project
    request = requests.AssembleMasterRequest(expected_revision=project.revision)
    monkeypatch.setattr(queue, "assembly_pool", RejectingPool())

    with pytest.raises(RuntimeError, match="queued"):
        queue.enqueue_master_assembly(project.id, request)

    history = queue.list_master_assembly_jobs(project.id)
    assert history["total"] == 1
    job = history["jobs"][0]
    assert job["status"] == "queued"
    assert PRIVATE_SENTINEL not in str(history)

    holding = HoldingPool()
    monkeypatch.setattr(queue, "assembly_pool", holding)
    retried = queue.enqueue_master_assembly(project.id, request)
    assert retried["id"] == job["id"]
    assert len(holding.submissions) == 1
    assert queue.list_master_assembly_jobs(project.id)["total"] == 1


@pytest.mark.skipif(
    not STRICT,
    reason="Expected-red API receipt contract runs only in dedicated QA41 workflow",
)
def test_authenticated_dispatch_503_must_include_committed_job_receipt(
    monkeypatch, ready_project,
):
    _, queue, _, project = ready_project
    monkeypatch.setenv("CHARACTER3D_STUDIO_TOKEN", "qa41-local-test-token")
    monkeypatch.setenv("CHARACTER3D_STUDIO_ORIGINS", "")
    # Follow the existing integration test's app/auth import isolation.
    for module in ("app.studio.server", "app.video.router"):
        sys.modules.pop(module, None)
    server = importlib.import_module("app.studio.server")
    path = f"/api/video/projects/{project.id}/assembly-jobs"
    headers = {"Authorization": "Bearer qa41-local-test-token"}
    monkeypatch.setattr(queue, "assembly_pool", HoldingPool())

    with TestClient(server.app) as client:
        # Startup recovery can run while the executor still accepts submissions.
        monkeypatch.setattr(queue, "assembly_pool", RejectingPool())
        response = client.post(
            path, json={"expected_revision": project.revision}, headers=headers,
        )
        assert response.status_code in (202, 503), response.status_code
        history_response = client.get(path, headers=headers)
        assert history_response.status_code == 200
        history = history_response.json()
        assert history["total"] == 1
        persisted_id = history["jobs"][0]["id"]
        assert history["jobs"][0]["status"] == "queued"

        body = response.json()
        detail = body.get("detail")
        detail = detail if isinstance(detail, dict) else {}
        receipt_id = body.get("id") or detail.get("job_id")
        # A 503 without a receipt is ambiguous: SQLite has committed a job.
        assert receipt_id == persisted_id, (
            "A committed assembly must return its job ID even if worker "
            "dispatch fails; a generic 503 loses the durable receipt"
        )
        assert PRIVATE_SENTINEL not in response.text
        assert "qa41-local-test-token" not in response.text

        holding = HoldingPool()
        monkeypatch.setattr(queue, "assembly_pool", holding)
        retry = client.post(
            path, json={"expected_revision": project.revision}, headers=headers,
        )
        assert retry.status_code == 202
        assert retry.json()["id"] == persisted_id
        assert len(holding.submissions) == 1
        assert client.get(path, headers=headers).json()["total"] == 1
