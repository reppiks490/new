"""QA117: cancellation survives independent API process exit and queue replay.

Actual independent Python interpreters and SQLite WAL. Project readiness,
worker submission and assembly are synthetic; no FFmpeg, model inference,
owner media, phone or concurrent live worker is exercised.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest


_PROJECT = "a" * 32
_OTHER = "f" * 32
_MASTER = "b" * 32

_CHILD = r"""
import json
import sys
from types import SimpleNamespace

from app.video.cinematic_requests import AssembleMasterRequest
from app.video.storage import put_video_record
import app.video.cinematic_assembly_jobs as queue

phase, mode, job_id = sys.argv[1:]
project_id = "a" * 32

if phase == "enqueue":
    queue.get_project = lambda identifier: SimpleNamespace(revision=3)
    queue.enforce_film_duration = lambda project: None
    queue.project_render_status = lambda identifier: {"ready_for_assembly": True}

    class HoldingPool:
        def submit(self, fn, *args, **kwargs):
            return object()

    queue.assembly_pool = HoldingPool()
    job = queue.enqueue_master_assembly(
        project_id, AssembleMasterRequest(expected_revision=3)
    )
    print(json.dumps({"id": job["id"], "status": job["status"]}), flush=True)

elif phase == "cancel":
    if mode == "foreign":
        try:
            queue.cancel_queued_master_assembly("f" * 32, job_id)
        except KeyError:
            result = {"outcome": "not_found"}
        else:
            raise AssertionError("Foreign project cancelled a private job")
    else:
        first = queue.cancel_queued_master_assembly(project_id, job_id)
        second = queue.cancel_queued_master_assembly(project_id, job_id)
        assert first["id"] == second["id"] == job_id
        assert first["status"] == second["status"] == "cancelled"
        result = {"outcome": "cancelled"}
    print(json.dumps(result), flush=True)

elif phase == "restart":
    calls = []

    def synthetic_assemble(identifier, request):
        calls.append([identifier, request.expected_revision])
        return put_video_record("video_master", {
            "project_id": identifier,
            "project_revision": request.expected_revision,
            "asset_id": "c" * 32,
            "asset_url": "/api/video/assets/" + "c" * 32 + ".mp4",
            "status": "ready",
            "probe": {"probe_metadata_verified": True},
            "sha256": "d" * 64,
            "actual_video_probe_verified": True,
        }, identifier="b" * 32)

    class InlinePool:
        def submit(self, fn, *args, **kwargs):
            fn(*args, **kwargs)
            return object()

    queue.assemble_project_master = synthetic_assemble
    queue.assembly_pool = InlinePool()
    first = queue.recover_assembly_queue()
    second = queue.recover_assembly_queue()
    page = queue.list_master_assembly_jobs(project_id)
    print(json.dumps({
        "calls": calls, "first": first, "second": second,
        "total": page["total"], "jobs": page["jobs"],
    }), flush=True)
else:
    raise AssertionError("Invalid QA117 child phase")
"""


def _run(root: Path, env: dict[str, str], phase: str, mode: str, job_id: str = "-") -> dict:
    completed = subprocess.run(
        [sys.executable, "-c", _CHILD, phase, mode, job_id],
        cwd=root, env=env, capture_output=True, text=True,
        check=False, timeout=45,
    )
    assert completed.returncode == 0, (
        f"QA117 independent {phase} process failed: {completed.stderr[-1000:]}"
    )
    return json.loads(completed.stdout.strip())


@pytest.mark.parametrize("mode", ["cancelled", "foreign"])
def test_cancelled_or_foreign_job_survives_crossprocess_restart_without_resurrection(
    monkeypatch, tmp_path: Path, mode: str,
):
    workspace = tmp_path / mode
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(workspace))
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(root), env.get("PYTHONPATH", "")) if value
    )

    admitted = _run(root, env, "enqueue", mode)
    assert admitted["status"] == "queued"
    job_id = admitted["id"]

    # Cancellation is performed in a NEW process, not the original API.
    cancellation = _run(root, env, "cancel", mode, job_id)
    assert cancellation["outcome"] == ("not_found" if mode == "foreign" else "cancelled")

    with sqlite3.connect(workspace / "studio.sqlite") as db:
        rows = db.execute(
            "SELECT id,data FROM records WHERE kind='video_assembly_job'"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == job_id
    assert json.loads(rows[0][1])["status"] == (
        "queued" if mode == "foreign" else "cancelled"
    )

    # Third interpreter performs genuine SQLite startup recovery and drain.
    restarted = _run(root, env, "restart", mode)
    assert restarted["first"]["interrupted"] == 0
    assert restarted["second"]["interrupted"] == 0
    assert restarted["total"] == 1
    assert len(restarted["jobs"]) == 1
    job = restarted["jobs"][0]
    assert job["id"] == job_id
    if mode == "cancelled":
        assert restarted["calls"] == []
        assert job["status"] == "cancelled"
        assert job["stage"] == "Cancelled"
        assert job["progress"] == 0
        assert "master_id" not in job
    else:
        assert restarted["calls"] == [[_PROJECT, 3]]
        assert job["status"] == "succeeded"
        assert job["master_id"] == _MASTER

    with sqlite3.connect(workspace / "studio.sqlite") as db:
        stored = db.execute(
            "SELECT data FROM records WHERE id=? AND kind='video_assembly_job'",
            (job_id,),
        ).fetchone()
        masters = db.execute(
            "SELECT id FROM records WHERE kind='video_master'"
        ).fetchall()
    assert stored is not None
    assert json.loads(stored[0])["status"] == job["status"]
    assert masters == ([] if mode == "cancelled" else [(_MASTER,)])
