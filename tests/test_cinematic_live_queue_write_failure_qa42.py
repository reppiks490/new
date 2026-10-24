"""QA42: a transient status-write failure must not wedge the live master queue.

Real SQLite queue/claim code, held executor and injected local failures.
No FFmpeg, generated footage, model inference, owner files or credentials.
"""
from __future__ import annotations

import importlib
import os
from types import SimpleNamespace

import pytest


PROJECT_A = "1" * 32
PROJECT_B = "2" * 32


class HeldPool:
    def __init__(self):
        self.submissions = 0

    def submit(self, fn, *args, **kwargs):
        self.submissions += 1
        return object()


def _two_queued_jobs(monkeypatch, tmp_path):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    queue = importlib.import_module("app.video.cinematic_assembly_jobs")
    requests = importlib.import_module("app.video.cinematic_requests")
    pool = HeldPool()
    monkeypatch.setattr(queue, "assembly_pool", pool)
    monkeypatch.setattr(queue, "get_project", lambda project_id: SimpleNamespace(revision=1))
    monkeypatch.setattr(queue, "enforce_film_duration", lambda project: None)
    monkeypatch.setattr(
        queue, "project_render_status",
        lambda project_id: {"ready_for_assembly": True},
    )
    request = requests.AssembleMasterRequest(expected_revision=1)
    first = queue.enqueue_master_assembly(PROJECT_A, request)
    second = queue.enqueue_master_assembly(PROJECT_B, request)
    assert first["id"] != second["id"]
    assert queue.get_master_assembly_job(PROJECT_A, first["id"])["status"] == "queued"
    assert queue.get_master_assembly_job(PROJECT_B, second["id"])["status"] == "queued"
    return queue, first, second


def _synthetic_encoder_failure(*args, **kwargs):
    raise RuntimeError("injected local encoder failure; no process launched")


def test_ordinary_encoder_failure_advances_durable_queue(monkeypatch, tmp_path):
    """Control: normal exception handling fails both jobs and drains the queue."""
    queue, first, second = _two_queued_jobs(monkeypatch, tmp_path)
    monkeypatch.setattr(queue, "assemble_project_master", _synthetic_encoder_failure)
    queue._drain()
    assert queue.get_master_assembly_job(PROJECT_A, first["id"])["status"] == "failed"
    assert queue.get_master_assembly_job(PROJECT_B, second["id"])["status"] == "failed"
    assert queue._claim_next() is None


@pytest.mark.skipif(
    os.getenv("CINEMATIC_REQUIRE_LIVE_QUEUE_RECOVERY_QA42") != "1",
    reason="Strict expected-red live-queue recovery contract runs in dedicated QA42 CI",
)
def test_one_transient_status_write_error_does_not_strand_live_queue(
    monkeypatch, tmp_path,
):
    """A one-shot failure updating a claimed job must not block later jobs forever.

    The second drain is an explicit simulated healthy dispatch, *not* a restart.
    An acceptable fix can fail/requeue the orphan with a lease or reconcile it;
    it must not silently leave a permanent running blocker.
    """
    queue, first, second = _two_queued_jobs(monkeypatch, tmp_path)
    monkeypatch.setattr(queue, "assemble_project_master", _synthetic_encoder_failure)
    original_store = queue._store_status
    attempts = 0

    def transient_store_failure(identifier, **updates):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("synthetic transient SQLite status write failure")
        return original_store(identifier, **updates)

    monkeypatch.setattr(queue, "_store_status", transient_store_failure)
    try:
        queue._drain()
    except OSError:
        pass  # The executor future would finish exceptionally in production.
    assert attempts == 1

    # Storage has recovered. A new healthy drain must not be blocked forever by
    # the orphaned 'running' record from the previous worker failure.
    monkeypatch.setattr(queue, "_store_status", original_store)
    queue._drain()

    first_status = queue.get_master_assembly_job(PROJECT_A, first["id"])["status"]
    second_status = queue.get_master_assembly_job(PROJECT_B, second["id"])["status"]
    assert first_status != "running", (
        "A failed worker left an unowned running claim that blocks all later jobs"
    )
    assert second_status == "failed", (
        "The next queued job never ran after the transient write failure cleared"
    )
