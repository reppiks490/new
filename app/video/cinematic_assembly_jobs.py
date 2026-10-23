"""Durable, locally executed cinematic master-assembly queue.

The HTTP request only writes a SQLite record and schedules work; actual FFmpeg
runs on a separate single-lane CPU pool, never blocking the iPhone request or
competing with the GPU inference executor. Designed for one local API server
process. Queued records survive restarts; in-flight ones fail closed on restart.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import re
import time
import uuid

from app.studio.storage import connection
from app.video.cinematic_requests import AssembleMasterRequest
from app.video.cinematic_service import (
    MasterAssemblyNotReady,
    ProjectRevisionConflict,
    assemble_project_master,
    get_project,
    project_render_status,
    enforce_film_duration,
)
from app.video.storage import get_video_record

assembly_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="local-master")
_MAX_OUTSTANDING = 32
_KIND = "video_assembly_job"


class AssemblyQueueFull(RuntimeError):
    pass


class AssemblyCancellationConflict(RuntimeError):
    """Only a queued assembly can be cancelled safely."""


def _now() -> float:
    return time.time()


def _store_status(identifier: str, **updates) -> dict | None:
    """CAS on running status; a late worker must not resurrect interrupted work."""
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT data FROM records WHERE id=? AND kind=?", (identifier, _KIND)
        ).fetchone()
        if row is None:
            return None
        payload = json.loads(row[0])
        if payload.get("status") != "running":
            return None
        payload.update(updates)
        db.execute(
            "UPDATE records SET data=?,updated=? WHERE id=? AND kind=?",
            (json.dumps(payload, allow_nan=False), _now(), identifier, _KIND),
        )
        return {"id": identifier, **payload}


def enqueue_master_assembly(project_id: str, request: AssembleMasterRequest) -> dict:
    """Idempotently enqueue the specified ready project revision.

    Readiness and revision are checked before the transaction for fast errors;
    actual master assembly revalidates both when it executes.
    """
    project = get_project(project_id)
    enforce_film_duration(project)
    if project.revision != request.expected_revision:
        raise ProjectRevisionConflict(project_id, request.expected_revision, project.revision)
    status = project_render_status(project_id)
    if not status["ready_for_assembly"]:
        raise MasterAssemblyNotReady("Project contains unrendered or unavailable shots")

    now = _now()
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        # The same project/revision can be requested concurrently from two devices.
        rows = db.execute(
            "SELECT id,data FROM records WHERE kind=? "
            "AND json_extract(data,'$.project_id')=? "
            "AND json_extract(data,'$.status') IN ('queued','running')",
            (_KIND, project_id),
        ).fetchall()
        for identifier, raw in rows:
            active = json.loads(raw)
            if (
                active.get("project_revision") == request.expected_revision
                and active.get("ffmpeg_path") == request.ffmpeg_path
            ):
                job = {"id": identifier, **active}
                break
        else:
            outstanding = db.execute(
                "SELECT COUNT(*) FROM records WHERE kind=? "
                "AND json_extract(data,'$.status') IN ('queued','running')",
                (_KIND,),
            ).fetchone()[0]
            if outstanding >= _MAX_OUTSTANDING:
                raise AssemblyQueueFull("Local master assembly queue is full")
            # Only neutral IDs and settings are stored; never the master prompt.
            identifier = uuid.uuid4().hex
            payload = {
                "project_id": project_id,
                "project_revision": request.expected_revision,
                "ffmpeg_path": request.ffmpeg_path,
                "status": "queued",
                "stage": "Queued",
                "created_at": now,
                "updated_at": now,
                "progress": 0,
            }
            db.execute(
                "INSERT INTO records(id,kind,data,updated) VALUES(?,?,?,?)",
                (identifier, _KIND, json.dumps(payload, allow_nan=False), now),
            )
            job = {"id": identifier, **payload}
    _dispatch()
    return job


def get_master_assembly_job(project_id: str, identifier: str) -> dict:
    job = get_video_record(_KIND, identifier)
    if job.get("project_id") != project_id:
        raise KeyError(identifier)
    return job


def cancel_queued_master_assembly(project_id: str, identifier: str) -> dict:
    """Atomically cancel an unclaimed job without touching FFmpeg.

    Both cancellation and _claim_next take BEGIN IMMEDIATE, so the queue
    never reports an already-claimed running encode as cancelled.
    """
    now = _now()
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT data FROM records WHERE id=? AND kind=?",
            (identifier, _KIND),
        ).fetchone()
        if row is None:
            raise KeyError(identifier)
        payload = json.loads(row[0])
        if payload.get("project_id") != project_id:
            raise KeyError(identifier)
        if payload.get("status") == "cancelled":
            return {"id": identifier, **payload}
        if payload.get("status") != "queued":
            raise AssemblyCancellationConflict(
                "Assembly has already started or finished; it cannot be cancelled via the queue."
            )
        payload.update(
            status="cancelled", stage="Cancelled", progress=0,
            error=None, finished_at=now, updated_at=now,
        )
        db.execute(
            "UPDATE records SET data=?,updated=? WHERE id=? AND kind=?",
            (json.dumps(payload, allow_nan=False), now, identifier, _KIND),
        )
    return {"id": identifier, **payload}


def list_master_assembly_jobs(
    project_id: str, *, limit: int = 50, offset: int = 0,
) -> dict:
    """Explicit pagination; never silently truncate the full history."""
    if not 1 <= limit <= 200 or offset < 0:
        raise ValueError("limit must be 1..200 and offset nonnegative")
    with connection() as db:
        total = db.execute(
            "SELECT COUNT(*) FROM records WHERE kind=? "
            "AND json_extract(data,'$.project_id')=?",
            (_KIND, project_id),
        ).fetchone()[0]
        rows = db.execute(
            "SELECT id,data FROM records WHERE kind=? "
            "AND json_extract(data,'$.project_id')=? "
            "ORDER BY updated DESC,id DESC LIMIT ? OFFSET ?",
            (_KIND, project_id, limit, offset),
        ).fetchall()
    return {
        "jobs": [{"id": identifier, **json.loads(raw)} for identifier, raw in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(rows) < total,
    }


def _claim_next() -> dict | None:
    """Atomically allow at most one assembly to run across API workers."""
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        running = db.execute(
            "SELECT COUNT(*) FROM records WHERE kind=? "
            "AND json_extract(data,'$.status')='running'", (_KIND,),
        ).fetchone()[0]
        if running:
            return None
        row = db.execute(
            "SELECT id,data FROM records WHERE kind=? "
            "AND json_extract(data,'$.status')='queued' "
            "ORDER BY updated ASC,id ASC LIMIT 1", (_KIND,),
        ).fetchone()
        if row is None:
            return None
        identifier, raw = row
        payload = json.loads(raw)
        # FFmpeg progress is not instrumented yet: do not invent a percentage.
        payload.update(status="running", stage="Assembling", progress=None,
                       started_at=_now(), updated_at=_now())
        db.execute(
            "UPDATE records SET data=?,updated=? WHERE id=? AND kind=?",
            (json.dumps(payload, allow_nan=False), _now(), identifier, _KIND),
        )
        return {"id": identifier, **payload}


def _validated_master_result(value: dict) -> dict:
    """Refuse to publish fabricated or unverified assembly artifacts."""
    if not isinstance(value, dict):
        raise ValueError("Master assembly result must be a record")
    if value.get("status") != "ready" or value.get("actual_video_probe_verified") is not True:
        raise ValueError("Master assembly was not verified")
    probe = value.get("probe")
    if not isinstance(probe, dict) or probe.get("probe_metadata_verified") is not True:
        raise ValueError("Master probe evidence is missing")
    identifiers = ("id", "asset_id")
    for key in identifiers:
        identifier = value.get(key)
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise ValueError("Master record identity is invalid")
    sha = value.get("sha256")
    if not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{64}", sha):
        raise ValueError("Master content hash is invalid")
    expected_url = f"/api/video/assets/{value['asset_id']}.mp4"
    if value.get("asset_url") != expected_url:
        raise ValueError("Master asset URL does not match verified identity")
    return value


def _execute_one(job: dict) -> None:
    try:
        result = _validated_master_result(assemble_project_master(
            job["project_id"],
            AssembleMasterRequest(
                expected_revision=job["project_revision"],
                ffmpeg_path=job["ffmpeg_path"],
            ),
        ))
    except ProjectRevisionConflict:
        _store_status(
            job["id"], status="failed", stage="Stale revision", progress=0,
            error="Project changed after queuing. Review edits and queue a new assembly.",
            finished_at=_now(),
        )
    except MasterAssemblyNotReady:
        _store_status(
            job["id"], status="failed", stage="Missing clips", progress=0,
            error="One or more completed shot files became unavailable. Re-render missing clips.",
            finished_at=_now(),
        )
    except Exception:
        # Internal filenames, prompts and executable errors must not appear in
        # a mobile-facing or unauthenticated log. Inspect private worker logs.
        _store_status(
            job["id"], status="failed", stage="Assembly failed", progress=0,
            error="Local master assembly failed. Inspect the private worker diagnostics.",
            finished_at=_now(),
        )
    else:
        _store_status(
            job["id"], status="succeeded", stage="Ready", progress=100,
            master_id=result["id"], asset_id=result["asset_id"],
            asset_url=result["asset_url"], sha256=result["sha256"],
            probe_metadata_verified=bool(result.get("actual_video_probe_verified")),
            finished_at=_now(),
        )


def _drain() -> None:
    while True:
        job = _claim_next()
        if job is None:
            return
        _execute_one(job)


def _dispatch() -> None:
    try:
        assembly_pool.submit(_drain)
    except RuntimeError as exc:
        # Request is durable, but this process could not start the worker.
        # Leave the record queued for replay on the next healthy startup.
        raise RuntimeError("Assembly queued, but local worker is unavailable") from exc


def recover_assembly_queue() -> dict:
    """One-server startup recovery.

    Running jobs cannot safely resume an interrupted FFmpeg subprocess, so
    mark them failed (retry requires explicit user action). Queued jobs remain
    eligible and are dispatched after the transaction.
    """
    now = _now()
    failed = 0
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        rows = db.execute(
            "SELECT id,data FROM records WHERE kind=? "
            "AND json_extract(data,'$.status')='running'", (_KIND,),
        ).fetchall()
        for identifier, raw in rows:
            payload = json.loads(raw)
            payload.update(
                status="failed", stage="Interrupted", progress=0,
                error="Worker restarted during assembly. Inspect the project and queue a new master.",
                finished_at=now, updated_at=now,
            )
            db.execute(
                "UPDATE records SET data=?,updated=? WHERE id=? AND kind=?",
                (json.dumps(payload, allow_nan=False), now, identifier, _KIND),
            )
            failed += 1
    _dispatch()
    return {"interrupted": failed}
