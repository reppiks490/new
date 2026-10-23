"""QA 14: repeated mobile retries must not amplify the local assembly executor queue.

Exercises the real SQLite-backed enqueue path with a held (not executing) pool.
No FFmpeg, model inference, owner media, network service or GPU is involved.
This is a draft RED contract, not a production implementation.
"""
from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest


PROJECT_ID = "6" * 32


class HeldPool:
    """Count queued futures without starting a worker or touching FFmpeg."""

    def __init__(self):
        self.submissions = 0

    def submit(self, fn, *args, **kwargs):
        self.submissions += 1
        return object()


class FailFirstPool(HeldPool):
    """Simulate a transient local worker scheduling failure."""

    def submit(self, fn, *args, **kwargs):
        self.submissions += 1
        if self.submissions == 1:
            raise RuntimeError("worker temporarily unavailable")
        return object()


def _queue(monkeypatch, tmp_path, pool):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    queue = importlib.import_module("app.video.cinematic_assembly_jobs")
    requests = importlib.import_module("app.video.cinematic_requests")
    monkeypatch.setattr(queue, "assembly_pool", pool)
    # Isolate dispatch accounting from readiness/model generation while using
    # the actual durable SQLite enqueue/idempotency/claim implementation.
    monkeypatch.setattr(queue, "get_project", lambda project_id: SimpleNamespace(revision=1))
    monkeypatch.setattr(queue, "enforce_film_duration", lambda project: None)
    monkeypatch.setattr(
        queue, "project_render_status",
        lambda project_id: {"ready_for_assembly": True},
    )
    return queue, requests.AssembleMasterRequest(expected_revision=1)


@pytest.mark.parametrize("worker_state", ["queued", "running"])
def test_duplicate_mobile_retries_do_not_enqueue_unbounded_drain_futures(
    monkeypatch, tmp_path, worker_state,
):
    pool = HeldPool()
    queue, request = _queue(monkeypatch, tmp_path, pool)
    original = queue.enqueue_master_assembly(PROJECT_ID, request)
    if worker_state == "running":
        claimed = queue._claim_next()
        assert claimed is not None and claimed["id"] == original["id"]
        assert claimed["status"] == "running"

    for _ in range(64):
        repeated = queue.enqueue_master_assembly(PROJECT_ID, request)
        assert repeated["id"] == original["id"]

    # The database's 32-outstanding-job limit is not an executor-future bound.
    # One durable job should not create 65 queued _drain futures under retries.
    assert queue.list_master_assembly_jobs(PROJECT_ID)["total"] == 1
    assert pool.submissions <= 2, (
        f"{pool.submissions} worker submissions for one durable "
        f"{worker_state} job: retries amplified the single-lane executor queue"
    )


def test_retry_after_dispatch_failure_still_wakes_persisted_job(monkeypatch, tmp_path):
    pool = FailFirstPool()
    queue, request = _queue(monkeypatch, tmp_path, pool)
    with pytest.raises(RuntimeError, match="Assembly queued"):
        queue.enqueue_master_assembly(PROJECT_ID, request)

    existing = queue.list_master_assembly_jobs(PROJECT_ID)
    assert existing["total"] == 1
    assert existing["jobs"][0]["status"] == "queued"

    retried = queue.enqueue_master_assembly(PROJECT_ID, request)
    assert retried["id"] == existing["jobs"][0]["id"]
    assert pool.submissions == 2, (
        "A duplicate request must be allowed to recover a previously "
        "persisted job after a failed worker submission"
    )
