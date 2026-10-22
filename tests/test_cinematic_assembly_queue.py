"""Durable cinematic assembly queue tests: no GPU or real FFmpeg required."""
from __future__ import annotations

import importlib
from concurrent.futures import ThreadPoolExecutor
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

A = "0" * 32
SCENE = "2" * 32
SHOT = "3" * 32


class HoldingPool:
    def __init__(self):
        self.submissions = []

    def submit(self, fn, *args, **kwargs):
        self.submissions.append((fn, args, kwargs))
        return object()


def _ready_project(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    storage = importlib.import_module("app.video.storage")
    jobs = importlib.import_module("app.video.cinematic_assembly_jobs")

    project = service.create_project(models.ProjectCreateRequest(
        title="Private film",
        master_prompt="VERY_PRIVATE_UNRENDERED_SCRIPT: A cinematic move.",
        target_duration_seconds=10,
        delivery_fps=24,
        delivery_resolution="480p",
        aspect_ratio="16:9",
    ))
    shot = models.CinematicShot(
        shot_id=SHOT, ordinal=1, title="Shot", prompt="Camera pan",
        duration_seconds=2,
    )
    scene = models.CinematicScene(
        scene_id=SCENE, ordinal=1, title="Scene",
        target_duration_seconds=2, shots=[shot],
    )
    project = service.update_project(
        project.id, models.ProjectUpdateRequest(expected_revision=1, scenes=[scene]),
    )
    asset_id = "4" * 32
    storage.video_asset_path(asset_id, "mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42source")
    record = storage.put_video_record("video_job", {
        "status": "succeeded", "project_id": project.id,
        "scene_id": SCENE, "shot_id": SHOT,
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
    return models, service, storage, jobs, project


def test_queue_is_durable_idempotent_private_and_nonblocking(monkeypatch, tmp_path):
    _, _, _, queue, project = _ready_project(monkeypatch, tmp_path)
    pool = HoldingPool()
    monkeypatch.setattr(queue, "assembly_pool", pool)
    requests = importlib.import_module("app.video.cinematic_requests")
    request = requests.AssembleMasterRequest(expected_revision=project.revision)
    first = queue.enqueue_master_assembly(project.id, request)
    second = queue.enqueue_master_assembly(project.id, request)
    assert first["id"] == second["id"]
    assert first["status"] == "queued"
    assert len(pool.submissions) == 2
    assert "PRIVATE" not in str(first)
    assert "prompt" not in str(first)
    stored = queue.get_master_assembly_job(project.id, first["id"])
    assert stored["status"] == "queued"
    assert queue.list_master_assembly_jobs(project.id)["total"] == 1

    # Simulate worker crash/restart before submission was claimed.
    recovered = queue.recover_assembly_queue()
    assert recovered["interrupted"] == 0
    assert queue.get_master_assembly_job(project.id, first["id"])["status"] == "queued"
    assert len(pool.submissions) == 3


def test_drain_executes_and_records_verified_master_without_leaking_scripts(monkeypatch, tmp_path):
    _, _, storage, queue, project = _ready_project(monkeypatch, tmp_path)
    monkeypatch.setattr(queue, "assembly_pool", HoldingPool())
    requests = importlib.import_module("app.video.cinematic_requests")
    job = queue.enqueue_master_assembly(
        project.id, requests.AssembleMasterRequest(expected_revision=project.revision),
    )
    invocations = []
    def fake_assemble(project_id, request):
        invocations.append((project_id, request.expected_revision))
        return {
            "id": "b" * 32, "asset_id": "a" * 32,
            "asset_url": "/api/video/assets/" + "a" * 32 + ".mp4",
            "sha256": "f" * 64, "actual_video_probe_verified": True,
        }
    monkeypatch.setattr(queue, "assemble_project_master", fake_assemble)
    queue._drain()
    latest = queue.get_master_assembly_job(project.id, job["id"])
    assert invocations == [(project.id, project.revision)]
    assert latest["status"] == "succeeded"
    assert latest["stage"] == "Ready"
    assert latest["progress"] == 100
    assert latest["probe_metadata_verified"] is True
    assert latest["asset_id"] == "a" * 32
    assert "VERY_PRIVATE" not in str(latest)
    assert queue._claim_next() is None


def test_running_assembly_fails_closed_on_restart_and_cannot_be_resurrected(monkeypatch, tmp_path):
    _, _, _, queue, project = _ready_project(monkeypatch, tmp_path)
    monkeypatch.setattr(queue, "assembly_pool", HoldingPool())
    requests = importlib.import_module("app.video.cinematic_requests")
    job = queue.enqueue_master_assembly(
        project.id, requests.AssembleMasterRequest(expected_revision=project.revision),
    )
    claimed = queue._claim_next()
    assert claimed and claimed["id"] == job["id"]
    assert queue._claim_next() is None
    outcome = queue.recover_assembly_queue()
    assert outcome["interrupted"] == 1
    interrupted = queue.get_master_assembly_job(project.id, job["id"])
    assert interrupted["status"] == "failed"
    assert interrupted["stage"] == "Interrupted"
    assert queue._store_status(job["id"], status="succeeded") is None
    retried = queue.enqueue_master_assembly(
        project.id, requests.AssembleMasterRequest(expected_revision=project.revision),
    )
    assert retried["id"] != job["id"]


def test_edited_project_fails_queued_assembly_without_publishing_success(monkeypatch, tmp_path):
    models, service, _, queue, project = _ready_project(monkeypatch, tmp_path)
    monkeypatch.setattr(queue, "assembly_pool", HoldingPool())
    requests = importlib.import_module("app.video.cinematic_requests")
    job = queue.enqueue_master_assembly(
        project.id, requests.AssembleMasterRequest(expected_revision=project.revision),
    )
    service.update_project(project.id, models.ProjectUpdateRequest(
        expected_revision=project.revision, title="Edited after queue",
    ))
    queue._drain()
    after = queue.get_master_assembly_job(project.id, job["id"])
    assert after["status"] == "failed"
    assert after["stage"] == "Stale revision"
    assert "asset_url" not in after


def test_assembly_history_pages_all_jobs_explicitly(monkeypatch, tmp_path):
    _, _, _, queue, project = _ready_project(monkeypatch, tmp_path)
    monkeypatch.setattr(queue, "assembly_pool", HoldingPool())
    requests = importlib.import_module("app.video.cinematic_requests")
    for _ in range(4):
        job = queue.enqueue_master_assembly(
            project.id,
            requests.AssembleMasterRequest(expected_revision=project.revision),
        )
        current = queue._claim_next()
        assert current and current["id"] == job["id"]
        queue._store_status(job["id"], status="failed", error="Synthetic failure")
    page1 = queue.list_master_assembly_jobs(project.id, limit=2, offset=0)
    page2 = queue.list_master_assembly_jobs(project.id, limit=2, offset=2)
    assert page1["total"] == 4
    assert page1["has_more"] is True
    assert page2["has_more"] is False
    assert len({r["id"] for r in page1["jobs"] + page2["jobs"]}) == 4
    with pytest.raises(ValueError):
        queue.list_master_assembly_jobs(project.id, limit=0)


def test_cancel_queued_assembly_is_idempotent_durable_and_not_claimable(monkeypatch, tmp_path):
    _, _, _, queue, project = _ready_project(monkeypatch, tmp_path)
    monkeypatch.setattr(queue, "assembly_pool", HoldingPool())
    requests = importlib.import_module("app.video.cinematic_requests")
    req = requests.AssembleMasterRequest(expected_revision=project.revision)
    job = queue.enqueue_master_assembly(project.id, req)
    cancelled = queue.cancel_queued_master_assembly(project.id, job["id"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["stage"] == "Cancelled"
    assert queue.cancel_queued_master_assembly(project.id, job["id"]) == cancelled
    assert queue._claim_next() is None
    queue.recover_assembly_queue()
    assert queue.get_master_assembly_job(project.id, job["id"])["status"] == "cancelled"
    # Cancelling releases capacity and allows an explicit new request.
    replacement = queue.enqueue_master_assembly(project.id, req)
    assert replacement["id"] != job["id"]
    assert replacement["status"] == "queued"


def test_cancel_running_assembly_rejected_and_cross_project_hidden(monkeypatch, tmp_path):
    _, _, _, queue, project = _ready_project(monkeypatch, tmp_path)
    monkeypatch.setattr(queue, "assembly_pool", HoldingPool())
    requests = importlib.import_module("app.video.cinematic_requests")
    job = queue.enqueue_master_assembly(
        project.id, requests.AssembleMasterRequest(expected_revision=project.revision),
    )
    with pytest.raises(KeyError):
        queue.cancel_queued_master_assembly("f" * 32, job["id"])
    assert queue.get_master_assembly_job(project.id, job["id"])["status"] == "queued"
    assert queue._claim_next()["id"] == job["id"]
    with pytest.raises(queue.AssemblyCancellationConflict):
        queue.cancel_queued_master_assembly(project.id, job["id"])
    assert queue.get_master_assembly_job(project.id, job["id"])["status"] == "running"
    queue._store_status(job["id"], status="succeeded", progress=100)
    with pytest.raises(queue.AssemblyCancellationConflict):
        queue.cancel_queued_master_assembly(project.id, job["id"])


def test_concurrent_submissions_have_exactly_one_active_record(monkeypatch, tmp_path):
    _, _, _, queue, project = _ready_project(monkeypatch, tmp_path)
    monkeypatch.setattr(queue, "assembly_pool", HoldingPool())
    requests = importlib.import_module("app.video.cinematic_requests")
    request = requests.AssembleMasterRequest(expected_revision=project.revision)
    with ThreadPoolExecutor(max_workers=6) as pool:
        identifiers = list(pool.map(
            lambda _: queue.enqueue_master_assembly(project.id, request)["id"], range(12),
        ))
    assert len(set(identifiers)) == 1
    history = queue.list_master_assembly_jobs(project.id)
    assert history["total"] == 1
    assert history["jobs"][0]["status"] == "queued"


def test_queue_capacity_released_after_cancel(monkeypatch, tmp_path):
    _, _, _, queue, first_project = _ready_project(monkeypatch, tmp_path)
    _, _, _, _, second_project = _ready_project(monkeypatch, tmp_path)
    _, _, _, _, third_project = _ready_project(monkeypatch, tmp_path)
    monkeypatch.setattr(queue, "assembly_pool", HoldingPool())
    monkeypatch.setattr(queue, "_MAX_OUTSTANDING", 2)
    requests = importlib.import_module("app.video.cinematic_requests")
    req = requests.AssembleMasterRequest(expected_revision=first_project.revision)
    first = queue.enqueue_master_assembly(first_project.id, req)
    second = queue.enqueue_master_assembly(second_project.id, req)
    with pytest.raises(queue.AssemblyQueueFull):
        queue.enqueue_master_assembly(third_project.id, req)
    assert second["status"] == "queued"
    cancelled = queue.cancel_queued_master_assembly(first_project.id, first["id"])
    assert cancelled["status"] == "cancelled"
    third = queue.enqueue_master_assembly(third_project.id, req)
    assert third["status"] == "queued"
    assert queue.list_master_assembly_jobs(first_project.id)["total"] == 1
    assert queue._claim_next()["id"] == second["id"]


def test_cancel_and_claim_race_has_single_winner(monkeypatch, tmp_path):
    _, _, _, queue, project = _ready_project(monkeypatch, tmp_path)
    monkeypatch.setattr(queue, "assembly_pool", HoldingPool())
    requests = importlib.import_module("app.video.cinematic_requests")
    job = queue.enqueue_master_assembly(
        project.id, requests.AssembleMasterRequest(expected_revision=project.revision),
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        claim_future = pool.submit(queue._claim_next)
        cancel_future = pool.submit(queue.cancel_queued_master_assembly, project.id, job["id"])
        claimed = claim_future.result()
        try:
            cancelled = cancel_future.result()
        except queue.AssemblyCancellationConflict:
            cancelled = None
    persisted = queue.get_master_assembly_job(project.id, job["id"])
    if claimed:
        assert claimed["id"] == job["id"]
        assert cancelled is None
        assert persisted["status"] == "running"
    else:
        assert cancelled is not None
        assert cancelled["status"] == "cancelled"
        assert persisted["status"] == "cancelled"
    assert queue._claim_next() is None


def test_async_assembly_api_is_authenticated_and_returns_202(monkeypatch, tmp_path):
    _, _, _, queue, project = _ready_project(monkeypatch, tmp_path)
    monkeypatch.setattr(queue, "assembly_pool", HoldingPool())
    monkeypatch.setenv("CHARACTER3D_STUDIO_TOKEN", "owner-local-token")
    monkeypatch.setenv("CHARACTER3D_STUDIO_ORIGINS", "")
    for module in ("app.studio.server", "app.video.router"):
        sys.modules.pop(module, None)
    server = importlib.import_module("app.studio.server")
    prefix = f"/api/video/projects/{project.id}/assembly-jobs"
    auth = {"Authorization": "Bearer owner-local-token"}
    with TestClient(server.app) as client:
        assert client.post(prefix, json={"expected_revision": 3}).status_code == 401
        assert client.get(prefix).status_code == 401
        response = client.post(prefix, json={"expected_revision": 3}, headers=auth)
        assert response.status_code == 202, response.text
        job = response.json()
        assert job["status"] == "queued"
        assert "VERY_PRIVATE" not in response.text
        detail = client.get(f"{prefix}/{job['id']}", headers=auth)
        assert detail.status_code == 200
        assert detail.json()["id"] == job["id"]
        listed = client.get(prefix, headers=auth)
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        assert client.get(f"{prefix}/{'f' * 32}", headers=auth).status_code == 404
        assert client.post(f"{prefix}/{job['id']}/cancel").status_code == 401
        cancel = client.post(f"{prefix}/{job['id']}/cancel", headers=auth)
        assert cancel.status_code == 200, cancel.text
        assert cancel.json()["status"] == "cancelled"
        assert client.get(f"{prefix}/{job['id']}", headers=auth).json()["status"] == "cancelled"
        assert client.post(f"{prefix}/{'f' * 32}/cancel", headers=auth).status_code == 404
        assert client.post(prefix, json={"expected_revision": 2}, headers=auth).status_code == 409
        assert client.post(
            prefix,
            json={"expected_revision": 3, "ffmpeg_path": "cmd.exe"},
            headers=auth,
        ).status_code == 422
