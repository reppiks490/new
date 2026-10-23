"""Async cancellation route and durable queue regression."""
import importlib

from test_cinematic_assembly_queue import HoldingPool, _ready_project


def test_cancelled_job_never_claimed(monkeypatch, tmp_path):
    _, _, _, queue, project = _ready_project(monkeypatch, tmp_path)
    monkeypatch.setattr(queue, "assembly_pool", HoldingPool())
    request = importlib.import_module("app.video.cinematic_requests").AssembleMasterRequest(
        expected_revision=project.revision,
    )
    job = queue.enqueue_master_assembly(project.id, request)
    cancelled = queue.cancel_queued_master_assembly(project.id, job["id"])
    assert cancelled["status"] == "cancelled"
    assert queue._claim_next() is None
