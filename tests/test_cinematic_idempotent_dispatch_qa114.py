"""QA114: duplicate idempotent master requests must not flood the local executor.

Synthetic SQLite records and a holding executor only. No FFmpeg, GPU, owner
media, network, or actual thread scheduling is involved.
"""
from __future__ import annotations

import importlib
from types import SimpleNamespace

from app.video.cinematic_requests import AssembleMasterRequest


class HoldingPool:
    """Record scheduled drain tasks without running them."""

    def __init__(self):
        self.submissions = []

    def submit(self, fn, *args, **kwargs):
        self.submissions.append((fn, args, kwargs))
        return object()


class DuplicateDispatchAmplification(AssertionError):
    """An idempotent request enqueued an additional executor drain."""


def test_duplicate_assembly_requests_do_not_amplify_executor_submissions(
    monkeypatch, tmp_path,
):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    queue = importlib.import_module("app.video.cinematic_assembly_jobs")
    project_id = "a" * 32
    revision = 3
    monkeypatch.setattr(
        queue, "get_project", lambda identifier: SimpleNamespace(revision=revision)
    )
    monkeypatch.setattr(queue, "enforce_film_duration", lambda project: None)
    monkeypatch.setattr(
        queue, "project_render_status",
        lambda identifier: {"ready_for_assembly": True},
    )
    pool = HoldingPool()
    monkeypatch.setattr(queue, "assembly_pool", pool)
    request = AssembleMasterRequest(expected_revision=revision)

    # Repeated mobile reconnect/retry of the SAME project and revision must
    # create one durable job and a bounded number of executor submissions.
    # The holding executor keeps the queued job from being claimed.
    ids = [
        queue.enqueue_master_assembly(project_id, request)["id"]
        for _ in range(64)
    ]
    assert len(set(ids)) == 1
    history = queue.list_master_assembly_jobs(project_id)
    assert history["total"] == 1
    assert history["jobs"][0]["status"] == "queued"

    # The first enqueue needs a wakeup. Identical retries must not enqueue
    # 63 additional _drain futures while the original job is still queued.
    if len(pool.submissions) != 1:
        raise DuplicateDispatchAmplification(
            f"one durable job scheduled {len(pool.submissions)} executor drains "
            "from 64 identical enqueue requests"
        )
