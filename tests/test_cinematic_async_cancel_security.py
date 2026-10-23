"""Restart-safe cancellation regression for cinematic master assembly."""
import importlib

from test_cinematic_assembly_queue import HoldingPool, _ready_project


def test_cancelled_job_stays_cancelled_after_restart(monkeypatch, tmp_path):
    _, _, _, queue, project = _ready_project(monkeypatch, tmp_path)
    pool = HoldingPool()
    monkeypatch.setattr(queue, "assembly_pool", pool)
    request = importlib.import_module("app.video.cinematic_requests").AssembleMasterRequest(
        expected_revision=project.revision,
    )
    job = queue.enqueue_master_assembly(project.id, request)
    cancelled = queue.cancel_queued_master_assembly(project.id, job["id"])
    assert cancelled["status"] == "cancelled"
    before = len(pool.submissions)
    queue.recover_assembly_queue()
    assert len(pool.submissions) == before + 1
    assert queue._claim_next() is None
    assert queue.get_master_assembly_job(project.id, job["id"])["status"] == "cancelled"
    assert queue.cancel_queued_master_assembly(project.id, job["id"]) == cancelled
