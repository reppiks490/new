"""QA121: four independent processes contend for one serialized assembly lane.

Real SQLite WAL and actual queue claim/CAS operations. No worker drain,
FFmpeg, model inference, HTTP, owner media or physical mobile device.
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
_CHILD = r"""
import json
from pathlib import Path
import sys
import time
from app.video import cinematic_assembly_jobs as queue

ready, start = map(Path, sys.argv[1:])
ready.write_text("ready", encoding="utf-8")
deadline = time.monotonic() + 30
while not start.exists():
    if time.monotonic() > deadline:
        raise TimeoutError("QA121 start gate timed out")
    time.sleep(0.01)
claimed = queue._claim_next()
print(json.dumps({"id": claimed["id"] if claimed else None}), flush=True)
"""


def _seed(monkeypatch, workspace: Path, first: str, second: str) -> None:
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(workspace))
    with connection() as db:
        for index, identifier in enumerate((first, second)):
            stamp = 100.0 + index
            payload = {
                "project_id": _PROJECT,
                "project_revision": 3,
                "ffmpeg_path": "ffmpeg",
                "status": "queued",
                "stage": "Queued",
                "progress": 0,
                "created_at": stamp,
                "updated_at": stamp,
            }
            db.execute(
                "INSERT INTO records(id,kind,data,updated) VALUES(?,?,?,?)",
                (identifier, "video_assembly_job", json.dumps(payload), stamp),
            )


def _claims(root: Path, env: dict[str, str], gate: Path, count: int) -> list[str | None]:
    gate.mkdir(parents=True)
    start = gate / "go"
    children = []
    try:
        for index in range(count):
            ready = gate / f"ready-{index}"
            children.append(subprocess.Popen(
                [sys.executable, "-u", "-c", _CHILD, str(ready), str(start)],
                cwd=root, env=env, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True,
            ))
        deadline = time.monotonic() + 40
        while not all((gate / f"ready-{i}").exists() for i in range(count)):
            assert not any(p.poll() is not None for p in children), (
                "A QA121 process exited before the shared gate"
            )
            assert time.monotonic() < deadline, "QA121 process startup timed out"
            time.sleep(0.02)
        start.write_text("go", encoding="utf-8")
        result = []
        for child in children:
            stdout, stderr = child.communicate(timeout=40)
            assert child.returncode == 0, f"QA121 isolated claim failed: {stderr[-1000:]}"
            result.append(json.loads(stdout.strip())["id"])
        return result
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=10)


def _durable(workspace: Path) -> dict[str, dict]:
    with sqlite3.connect(workspace / "studio.sqlite") as db:
        rows = db.execute(
            "SELECT id,data FROM records WHERE kind='video_assembly_job'"
        ).fetchall()
    return {identifier: json.loads(raw) for identifier, raw in rows}


def test_independent_processes_never_double_claim_or_skip_fifo_after_terminal(
    monkeypatch, tmp_path: Path,
):
    root = Path(__file__).resolve().parents[1]
    for round_index in range(4):
        workspace = tmp_path / f"round-{round_index}"
        first = f"{round_index * 2 + 1:032x}"
        second = f"{round_index * 2 + 2:032x}"
        _seed(monkeypatch, workspace, first, second)
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(
            part for part in (str(root), env.get("PYTHONPATH", "")) if part
        )

        # Four separate interpreters compete while two queued jobs exist.
        # Only the oldest job may be claimed; the other stays queued.
        wave1 = _claims(root, env, workspace / "wave1", 4)
        assert wave1.count(first) == 1
        assert wave1.count(None) == 3
        assert second not in wave1
        durable = _durable(workspace)
        assert len(durable) == 2
        assert durable[first]["status"] == "running"
        assert durable[second]["status"] == "queued"
        assert queue._claim_next() is None

        # Synthetic terminal transition, not a completed media encode.
        assert queue._store_status(
            first, status="failed", stage="QA121 synthetic release",
            progress=0, error=None,
        )["status"] == "failed"
        assert queue._store_status(
            first, status="succeeded", stage="Invalid late completion",
            progress=100,
        ) is None

        # A fresh independent-process wave can now claim exactly the next job.
        wave2 = _claims(root, env, workspace / "wave2", 3)
        assert wave2.count(second) == 1
        assert wave2.count(None) == 2
        durable = _durable(workspace)
        assert durable[first]["status"] == "failed"
        assert durable[second]["status"] == "running"
        assert queue._store_status(
            second, status="failed", stage="QA121 synthetic release",
            progress=0, error=None,
        )["status"] == "failed"
        assert queue._claim_next() is None
        durable = _durable(workspace)
        assert [durable[key]["status"] for key in (first, second)] == [
            "failed", "failed",
        ]
