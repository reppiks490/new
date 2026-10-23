"""QA 13: SQLite-backed offset pagination must not hide a newly active master job.

Test-first server-side counterpart to the mocked mobile reconnect scan in PR #36.
No FFmpeg, real media, model inference, network device, or owner credentials.
"""
from __future__ import annotations

import importlib

import pytest

from test_cinematic_assembly_queue import HoldingPool, _ready_project


@pytest.mark.parametrize("claim_oldest", [False, True], ids=["stable-control", "oldest-job-becomes-running"])
def test_cinematic_queue_history_pages_preserve_job_discovery_during_claim(
    monkeypatch, tmp_path, claim_oldest,
):
    models, service, _, queue, project = _ready_project(monkeypatch, tmp_path)
    monkeypatch.setattr(queue, "assembly_pool", HoldingPool())

    # Stable clock makes the DB ordering and the simulated worker transition
    # deterministic across platforms and Python versions.
    ticks = iter(range(1000, 1100))
    monkeypatch.setattr(queue, "_now", lambda: float(next(ticks)))
    request_type = importlib.import_module(
        "app.video.cinematic_requests"
    ).AssembleMasterRequest

    jobs = []
    for ordinal in range(3):
        if ordinal:
            # Retitling changes the revision but does not invalidate rendered
            # shot intent. This legitimately permits another queued job while
            # earlier revisions remain queued.
            project = service.update_project(
                project.id,
                models.ProjectUpdateRequest(
                    expected_revision=project.revision,
                    title=f"Private project revision {ordinal}",
                ),
            )
        assert service.project_render_status(project.id)["ready_for_assembly"]
        jobs.append(queue.enqueue_master_assembly(
            project.id, request_type(expected_revision=project.revision)
        ))

    first = queue.list_master_assembly_jobs(project.id, limit=2, offset=0)
    assert first["total"] == 3
    assert first["has_more"] is True
    assert [item["id"] for item in first["jobs"]] == [
        jobs[2]["id"], jobs[1]["id"],
    ]

    if claim_oldest:
        # The real worker claim advances the oldest queued job to running and
        # updates records.updated, moving it in front of the already-read page.
        claimed = queue._claim_next()
        assert claimed is not None
        assert claimed["id"] == jobs[0]["id"]
        assert claimed["status"] == "running"

    second = queue.list_master_assembly_jobs(project.id, limit=2, offset=2)
    assert second["total"] == 3
    assert second["has_more"] is False
    scanned = first["jobs"] + second["jobs"]
    scanned_ids = [item["id"] for item in scanned]
    assert "VERY_PRIVATE_UNRENDERED_SCRIPT" not in str(scanned)

    # The stable control passes. With a claim between pages, the current
    # updated-DESC/OFFSET query repeats a prior ID and misses the running job.
    # A future server-side active-job endpoint or stable snapshot/cursor
    # protocol should provide complete reconnect discovery without exposing
    # raw scripts or relying solely on client retry heuristics.
    assert len(scanned_ids) == len(set(scanned_ids)), (
        "History pages repeated an ID after a worker claim; mobile reconnect "
        "can miss an active job while paging by mutable updated timestamps"
    )
    assert set(scanned_ids) == {job["id"] for job in jobs}, (
        "An active job disappeared from offset-paginated history after claim"
    )
