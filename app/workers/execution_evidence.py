from __future__ import annotations

import hashlib
import json
import subprocess
import time
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

from app.workers.blender import BlenderInvocation


class ExecutionMode(str, Enum):
    LIVE = 'live'
    SYNTHETIC = 'synthetic'
    COMPILED_ONLY = 'compiled_only'


class ExecutionEvidence(BaseModel):
    stage: str
    mode: ExecutionMode
    success: bool
    tool: str
    started_at: float
    finished_at: float
    artifact_sha256: str | None = None
    receipt_sha256: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_live_success(self) -> bool:
        return self.mode == ExecutionMode.LIVE and self.success


class BlenderExecutionReceipt(BaseModel):
    schema_version: str = 'character3d-blender-execution-v1'
    command_sha256: str
    manifest_sha256: str | None = None
    worker_receipt_sha256: str | None = None
    returncode: int
    success: bool
    started_at: float
    finished_at: float
    duration_seconds: float
    stdout_sha256: str
    stderr_sha256: str
    worker_status: str | None = None
    error: str | None = None


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8', errors='replace')).hexdigest()


def _command_sha(invocation: BlenderInvocation) -> str:
    payload = json.dumps(invocation.command, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def execute_blender_with_receipt(
    invocation: BlenderInvocation,
    *,
    manifest_path: str | Path | None = None,
    worker_receipt_path: str | Path | None = None,
    timeout_seconds: int = 60 * 60,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> BlenderExecutionReceipt:
    started = time.time()
    error: str | None = None
    try:
        cp = runner(
            invocation.command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=invocation.env or None,
        )
        returncode = int(cp.returncode)
        stdout = cp.stdout or ''
        stderr = cp.stderr or ''
    except subprocess.TimeoutExpired as exc:
        returncode = -9
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or '')
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or '')
        error = f'Blender process exceeded timeout of {timeout_seconds}s.'
    except OSError as exc:
        returncode = -1
        stdout = ''
        stderr = str(exc)
        error = f'Blender process could not start: {exc}'

    worker_status: str | None = None
    worker_sha: str | None = None
    if worker_receipt_path:
        p = Path(worker_receipt_path)
        if p.is_file():
            worker_sha = sha256_file(p)
            try:
                payload = json.loads(p.read_text(encoding='utf-8'))
                worker_status = str(payload.get('status', '')).lower() or None
            except (OSError, json.JSONDecodeError, TypeError):
                worker_status = 'invalid_receipt'
        else:
            worker_status = 'missing_receipt'

    manifest_sha = sha256_file(manifest_path) if manifest_path and Path(manifest_path).is_file() else None
    process_ok = returncode == 0
    worker_ok = worker_receipt_path is None or worker_status in {'succeeded', 'success', 'completed'}
    success = process_ok and worker_ok and error is None
    if process_ok and not worker_ok and error is None:
        error = f'Blender process exited successfully but worker receipt status was {worker_status!r}.'

    finished = time.time()
    return BlenderExecutionReceipt(
        command_sha256=_command_sha(invocation),
        manifest_sha256=manifest_sha,
        worker_receipt_sha256=worker_sha,
        returncode=returncode,
        success=success,
        started_at=started,
        finished_at=finished,
        duration_seconds=max(0.0, finished - started),
        stdout_sha256=_sha256_text(stdout),
        stderr_sha256=_sha256_text(stderr),
        worker_status=worker_status,
        error=error,
    )
