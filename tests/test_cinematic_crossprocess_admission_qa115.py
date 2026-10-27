"""QA115: cross-process SQLite queue admission, not worker/process safety.

Uses real independent Python interpreters and disposable SQLite WAL storage.
The project-readiness check and executor are deliberately stubbed. No owner
media, FFmpeg, model inference, network, or live worker is involved.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

import pytest

from app.studio.storage import connection


# Kept as a separate interpreter script so process isolation is real, even
# when pytest runs under a worker with imported app modules or thread pools.
_CHILD = r"""
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

from app.video.cinematic_requests import AssembleMasterRequest
import app.video.cinematic_assembly_jobs as queue

mode, index, ready_path, start_path = sys.argv[1:]
queue.get_project = lambda project_id: SimpleNamespace(revision=3)
queue.enforce_film_duration = lambda project: None
queue.project_render_status = lambda project_id: {"ready_for_assembly": True}
if mode == "capacity":
    queue._MAX_OUTSTANDING = 2

class HoldingPool:
    def submit(self, fn, *args, **kwargs):
        return object()

queue.assembly_pool = HoldingPool()
Path(ready_path).write_text("ready", encoding="utf-8")
deadline = time.monotonic() + 35
while not Path(start_path).exists():
    if time.monotonic() > deadline:
        raise RuntimeError("QA115 start barrier timed out")
    time.sleep(0.02)

project_id = "a" * 32 if mode == "duplicate" else f"{int(index) + 1:032x}"
try:
    result = queue.enqueue_master_assembly(
        project_id, AssembleMasterRequest(expected_revision=3)
    )
except queue.AssemblyQueueFull:
    print(json.dumps({"kind": "full"}), flush=True)
else:
    print(json.dumps({
        "kind": "accepted", "id": result["id"],
        "project_id": result["project_id"], "status": result["status"]
    }), flush=True)
"""


@pytest.mark.parametrize("mode,expected_count", [("duplicate", 1), ("capacity", 2)])
def test_independent_processes_share_atomic_admission_without_worker_claims(
    monkeypatch, tmp_path: Path, mode: str, expected_count: int
):
    workspace = tmp_path / mode
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(workspace))
    # Initialize schema before releasing the competing independent processes.
    with connection():
        pass

    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(root), env.get("PYTHONPATH", "")) if part
    )
    start = tmp_path / f"{mode}-start"
    children = []
    ready = []
    try:
        for index in range(4):
            marker = tmp_path / f"{mode}-ready-{index}"
            ready.append(marker)
            children.append(subprocess.Popen(
                [sys.executable, "-c", _CHILD, mode, str(index), str(marker), str(start)],
                cwd=root, env=env, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True,
            ))

        deadline = time.monotonic() + 40
        while not all(marker.exists() for marker in ready):
            if any(child.poll() is not None for child in children):
                raise AssertionError("QA115 child exited before the admission barrier")
            if time.monotonic() > deadline:
                raise AssertionError("QA115 child startup exceeded 40 seconds")
            time.sleep(0.05)
        start.write_text("go", encoding="utf-8")

        responses = []
        for child in children:
            stdout, stderr = child.communicate(timeout=40)
            assert child.returncode == 0, f"isolated admission child failed: {stderr[-1200:]}"
            responses.append(json.loads(stdout.strip()))

        accepted = [response for response in responses if response["kind"] == "accepted"]
        rejected = [response for response in responses if response["kind"] == "full"]
        assert len(accepted) == (4 if mode == "duplicate" else 2)
        assert len(rejected) == (0 if mode == "duplicate" else 2)
        assert all(row["status"] == "queued" for row in accepted)

        with sqlite3.connect(workspace / "studio.sqlite") as db:
            persisted = db.execute(
                "SELECT id,data FROM records WHERE kind='video_assembly_job'"
            ).fetchall()
        assert len(persisted) == expected_count
        assert all(json.loads(payload)["status"] == "queued" for _, payload in persisted)
        assert {row["id"] for row in accepted} == {row_id for row_id, _ in persisted}
        if mode == "duplicate":
            assert len({row["id"] for row in accepted}) == 1
            assert {row["project_id"] for row in accepted} == {"a" * 32}
        else:
            assert len({row["project_id"] for row in accepted}) == 2
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.communicate()
