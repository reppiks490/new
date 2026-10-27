"""QA120: independent Python processes race cancellation against a queue claim.

Uses real SQLite WAL transactions and two distinct interpreters per round.
No FastAPI, FFmpeg, GPU, owner media, model inference, or live worker execution.
Complements QA117 restart/cancellation and Helper 1 QA119's threaded HTTP race.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

from app.studio.storage import connection
from app.video import cinematic_assembly_jobs as queue

_PROJECT = "a" * 32
_PRIVATE = "QA120_PRIVATE_SCRIPT_MARKER_NEVER_PUBLIC"

_CHILD = r"""
import json
import os
from pathlib import Path
import sys
import time

from app.video import cinematic_assembly_jobs as queue

action, project_id, job_id, gate_dir = sys.argv[1:]
gate = Path(gate_dir)
(gate / (action + ".ready")).write_text("ready")
deadline = time.monotonic() + 20
while not (gate / "go").exists():
    if time.monotonic() > deadline:
        raise TimeoutError("QA120 process gate timed out")
    time.sleep(0.005)

if action == "claim":
    claimed = queue._claim_next()
    result = {"action": action, "id": claimed["id"] if claimed else None}
elif action == "cancel":
    try:
        cancelled = queue.cancel_queued_master_assembly(project_id, job_id)
    except queue.AssemblyCancellationConflict:
        result = {"action": action, "outcome": "conflict"}
    else:
        result = {
            "action": action,
            "outcome": "cancelled",
            "id": cancelled["id"],
            "status": cancelled["status"],
        }
else:
    raise AssertionError("Invalid QA120 child action")
print(json.dumps(result), flush=True)
"""


def _seed_job(monkeypatch, workspace: Path, identifier: str) -> None:
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(workspace))
    payload = {
        "project_id": _PROJECT,
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


def _race(root: Path, env: dict[str, str], job_id: str, gate: Path) -> dict:
    gate.mkdir(parents=True)
    processes = {
        action: subprocess.Popen(
            [sys.executable, "-u", "-c", _CHILD, action, _PROJECT, job_id, str(gate)],
            cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        )
        for action in ("claim", "cancel")
    }
    try:
        deadline = time.monotonic() + 25
        while not all((gate / (action + ".ready")).exists() for action in processes):
            if time.monotonic() > deadline:
                raise AssertionError("Independent workers did not reach the shared gate")
            if any(p.poll() is not None for p in processes.values()):
                raise AssertionError("A worker exited before the race gate")
            time.sleep(0.01)
        (gate / "go").write_text("go")
        results = {}
        for action, proc in processes.items():
            stdout, stderr = proc.communicate(timeout=30)
            assert proc.returncode == 0, (
                f"QA120 {action} process failed: {stderr[-1000:]}"
            )
            assert _PRIVATE not in stdout + stderr
            results[action] = json.loads(stdout.strip())
        return results
    finally:
        for proc in processes.values():
            if proc.poll() is None:
                proc.kill()
                proc.communicate(timeout=10)


def test_independent_process_cancel_and_claim_have_one_durable_winner(
    monkeypatch, tmp_path: Path,
):
    root = Path(__file__).resolve().parents[1]
    for round_index in range(8):
        workspace = tmp_path / f"round-{round_index}"
        identifier = f"{round_index + 1:032x}"
        _seed_job(monkeypatch, workspace, identifier)
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(
            item for item in (str(root), env.get("PYTHONPATH", "")) if item
        )
        results = _race(root, env, identifier, workspace / "gate")
        claimed = results["claim"]["id"]
        cancellation = results["cancel"]["outcome"]

        with sqlite3.connect(workspace / "studio.sqlite") as db:
            records = db.execute(
                "SELECT id,data FROM records WHERE kind='video_assembly_job'"
            ).fetchall()
        assert len(records) == 1
        assert records[0][0] == identifier
        durable = json.loads(records[0][1])
        assert durable["project_id"] == _PROJECT
        assert _PRIVATE not in records[0][1]

        if cancellation == "cancelled":
            assert claimed is None
            assert results["cancel"]["id"] == identifier
            assert results["cancel"]["status"] == "cancelled"
            assert durable["status"] == "cancelled"
            assert queue._claim_next() is None
            assert queue.cancel_queued_master_assembly(_PROJECT, identifier)["status"] == "cancelled"
        else:
            assert cancellation == "conflict"
            assert claimed == identifier
            assert durable["status"] == "running"
            # Synthetic cleanup only; no media assembly or live worker.
            updated = queue._store_status(
                identifier, status="failed", stage="QA120 synthetic cleanup",
                progress=0, error=None,
            )
            assert updated is not None
            assert updated["status"] == "failed"
            assert queue._claim_next() is None
