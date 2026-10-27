"""QA116: queued cinematic assembly survives an API process exit and replays once.

Real independent Python processes + disposable SQLite WAL. Readiness, executor
and master assembly are synthetic stand-ins. No FFmpeg, model inference,
private owner media, phone, network or multi-worker live recovery is tested.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest


_PROJECT_ID = "a" * 32
_MASTER_ID = "b" * 32
_ASSET_ID = "c" * 32
_SHA256 = "d" * 64

_CHILD = r"""
import json
import sys
from types import SimpleNamespace

from app.video.cinematic_requests import AssembleMasterRequest
from app.video.storage import put_video_record
import app.video.cinematic_assembly_jobs as queue

phase, submission_mode = sys.argv[1:]
project_id = "a" * 32
if phase == "enqueue":
    queue.get_project = lambda identifier: SimpleNamespace(revision=3)
    queue.enforce_film_duration = lambda project: None
    queue.project_render_status = lambda identifier: {"ready_for_assembly": True}

    class HoldingPool:
        def submit(self, fn, *args, **kwargs):
            return object()

    class RejectPool:
        def submit(self, fn, *args, **kwargs):
            raise RuntimeError("SYNTHETIC_PRIVATE_EXECUTOR_DIAGNOSTIC")

    queue.assembly_pool = RejectPool() if submission_mode == "rejected" else HoldingPool()
    try:
        job = queue.enqueue_master_assembly(
            project_id, AssembleMasterRequest(expected_revision=3)
        )
    except RuntimeError as exc:
        if submission_mode != "rejected":
            raise
        print(json.dumps({"kind": "rejected", "message": str(exc)}), flush=True)
    else:
        if submission_mode == "rejected":
            raise AssertionError("The rejecting executor was unexpectedly accepted")
        print(json.dumps({"kind": "held", "id": job["id"]}), flush=True)

elif phase == "restart":
    calls = []

    def fake_assemble(identifier, request):
        calls.append((identifier, request.expected_revision))
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

    queue.assemble_project_master = fake_assemble
    queue.assembly_pool = InlinePool()
    first = queue.recover_assembly_queue()
    second = queue.recover_assembly_queue()
    page = queue.list_master_assembly_jobs(project_id)
    print(json.dumps({
        "first_interrupted": first["interrupted"],
        "second_interrupted": second["interrupted"],
        "calls": calls,
        "total": page["total"],
        "jobs": page["jobs"],
    }), flush=True)
else:
    raise AssertionError("Invalid QA116 phase")
"""


def _child(root: Path, env: dict[str, str], phase: str, mode: str) -> dict:
    result = subprocess.run(
        [sys.executable, "-c", _CHILD, phase, mode],
        cwd=root, env=env, capture_output=True, text=True, timeout=45,
        check=False,
    )
    assert result.returncode == 0, (
        f"QA116 isolated {phase} process failed: {result.stderr[-1200:]}"
    )
    assert "SYNTHETIC_PRIVATE_EXECUTOR_DIAGNOSTIC" not in result.stdout
    return json.loads(result.stdout.strip())


@pytest.mark.parametrize("mode", ["held", "rejected"])
def test_queued_job_replays_once_after_independent_process_exit(
    monkeypatch, tmp_path: Path, mode: str
):
    workspace = tmp_path / mode
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(workspace))
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(root), env.get("PYTHONPATH", "")) if part
    )

    # First interpreter persists a job, then exits without claiming it.
    admitted = _child(root, env, "enqueue", mode)
    assert admitted["kind"] == mode
    if mode == "rejected":
        assert admitted["message"] == "Assembly queued, but local worker is unavailable"

    with sqlite3.connect(workspace / "studio.sqlite") as db:
        records = db.execute(
            "SELECT id,data FROM records WHERE kind='video_assembly_job'"
        ).fetchall()
    assert len(records) == 1
    job_id, raw = records[0]
    assert json.loads(raw)["status"] == "queued"
    assert "SYNTHETIC_PRIVATE_EXECUTOR_DIAGNOSTIC" not in raw
    if mode == "held":
        assert admitted["id"] == job_id

    # A NEW interpreter performs startup replay. Only the assembly callback
    # is fake: SQLite claim, terminal CAS, recovery and history are genuine.
    restarted = _child(root, env, "restart", mode)
    assert restarted["first_interrupted"] == 0
    assert restarted["second_interrupted"] == 0
    assert restarted["calls"] == [[_PROJECT_ID, 3]]
    assert restarted["total"] == 1
    assert len(restarted["jobs"]) == 1
    finished = restarted["jobs"][0]
    assert finished["id"] == job_id
    assert finished["status"] == "succeeded"
    assert finished["master_id"] == _MASTER_ID
    assert finished["asset_id"] == _ASSET_ID
    assert finished["sha256"] == _SHA256
    assert finished["progress"] == 100
    assert "SYNTHETIC_PRIVATE_EXECUTOR_DIAGNOSTIC" not in str(finished)

    # Terminal state is actually durable after both child processes exit.
    with sqlite3.connect(workspace / "studio.sqlite") as db:
        durable = db.execute(
            "SELECT data FROM records WHERE id=? AND kind='video_assembly_job'",
            (job_id,),
        ).fetchone()
        masters = db.execute(
            "SELECT id FROM records WHERE kind='video_master'"
        ).fetchall()
    assert durable is not None
    assert json.loads(durable[0])["status"] == "succeeded"
    assert masters == [(_MASTER_ID,)]
