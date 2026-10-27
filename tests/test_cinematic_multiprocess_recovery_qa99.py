"""QA99: real-process SQLite recovery isolation (no FFmpeg or model inference).

A second API process must not label another still-live worker's claimed job
"Interrupted". The existing one-server design has no durable owner/lease.
This test deliberately reproduces that unsupported multi-process boundary.
All records and child processes are synthetic and confined to tmp_path.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.studio.storage import connection
from app.video import cinematic_assembly_jobs as queue


# Execute the real queue module in a distinct OS process. No mocked claim,
# no real FFmpeg, no private assets, no server or paid generation.
_CLAIM_SCRIPT = """
import json
import sys
from app.video import cinematic_assembly_jobs as queue

claimed = queue._claim_next()
print(json.dumps({"claimed": claimed["id"] if claimed else None}), flush=True)
if sys.argv[1] == "hold":
    sys.stdin.readline()
    updated = queue._store_status(
        claimed["id"], status="failed", stage="Synthetic worker completed",
        progress=0, error="Synthetic QA only",
    )
    print(json.dumps({"cas_succeeded": updated is not None}), flush=True)
"""


def _seed_queued_job(monkeypatch, workspace: Path) -> str:
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(workspace))
    identifier = "a" * 32
    payload = {
        "project_id": "b" * 32,
        "project_revision": 3,
        "ffmpeg_path": "ffmpeg",
        "status": "queued",
        "stage": "Queued",
        "progress": 0,
        "created_at": 100.0,
        "updated_at": 100.0,
    }
    with connection() as db:
        db.execute(
            "INSERT INTO records(id,kind,data,updated) VALUES(?,?,?,?)",
            (identifier, "video_assembly_job", json.dumps(payload), 100.0),
        )
    # Suppress only the local thread dispatch; actual SQLite transitions remain real.
    monkeypatch.setattr(queue, "_dispatch", lambda: None)
    return identifier


def _child_env() -> dict[str, str]:
    return os.environ.copy()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_orphaned_claim_is_failed_closed_after_worker_exits(monkeypatch, tmp_path):
    """Positive control: a genuinely exited claimant must be recoverable."""
    identifier = _seed_queued_job(monkeypatch, tmp_path)
    completed = subprocess.run(
        [sys.executable, "-u", "-c", _CLAIM_SCRIPT, "exit"],
        cwd=_repo_root(), env=_child_env(), text=True,
        capture_output=True, check=True, timeout=35,
    )
    assert json.loads(completed.stdout.strip())["claimed"] == identifier
    assert queue.get_master_assembly_job("b" * 32, identifier)["status"] == "running"

    recovered = queue.recover_assembly_queue()
    assert recovered["interrupted"] == 1
    final = queue.get_master_assembly_job("b" * 32, identifier)
    assert final["status"] == "failed"
    assert final["stage"] == "Interrupted"


class LiveWorkerRecoveryConflict(AssertionError):
    """The expected, specific unsupported multi-process recovery failure."""


@pytest.mark.xfail(
    strict=True,
    raises=LiveWorkerRecoveryConflict,
    reason="Unfixed: second API startup interrupts a live worker; no durable owner lease",
)
def test_second_process_startup_does_not_interrupt_live_worker(monkeypatch, tmp_path):
    """Negative control: real live claimant is currently failed by startup.

    The desired multi-process behavior is zero interruptions and an accepted
    terminal CAS from the original worker. This intentionally starts RED.
    """
    identifier = _seed_queued_job(monkeypatch, tmp_path)
    worker = subprocess.Popen(
        [sys.executable, "-u", "-c", _CLAIM_SCRIPT, "hold"],
        cwd=_repo_root(), env=_child_env(), text=True,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    recovered = None
    tail = ""
    stderr = ""
    try:
        assert worker.stdout is not None
        first = worker.stdout.readline()
        assert first, "Child failed before claim"
        assert json.loads(first)["claimed"] == identifier
        assert worker.poll() is None, "Original claimant must remain alive"
        assert queue.get_master_assembly_job("b" * 32, identifier)["status"] == "running"
        assert queue._claim_next() is None  # Existing cross-process claim lock works.

        # Simulates a second API process booting against the same SQLite WAL.
        recovered = queue.recover_assembly_queue()
    finally:
        if worker.poll() is None:
            try:
                tail, stderr = worker.communicate(input="\n", timeout=35)
            except subprocess.TimeoutExpired:
                worker.kill()
                tail, stderr = worker.communicate(timeout=10)
                pytest.fail("Synthetic claimant failed to exit after release")
        else:
            tail, stderr = worker.communicate(timeout=10)

    assert worker.returncode == 0, stderr[-1000:]
    assert recovered is not None
    if recovered["interrupted"] != 0:
        assert json.loads(tail.strip())["cas_succeeded"] is False
        assert queue.get_master_assembly_job("b" * 32, identifier)["stage"] == "Interrupted"
        raise LiveWorkerRecoveryConflict(
            "Second process startup invalidated a still-live worker's claim"
        )
    assert json.loads(tail.strip())["cas_succeeded"] is True
    assert queue.get_master_assembly_job("b" * 32, identifier)["stage"] == (
        "Synthetic worker completed"
    )
