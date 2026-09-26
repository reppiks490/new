from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


CheckpointStatus = Literal['succeeded', 'failed', 'skipped']


class StageCheckpoint(BaseModel):
    schema_version: str = 'character3d-stage-checkpoint-v1'
    job_id: str
    stage: str
    attempt: int
    status: CheckpointStatus
    input_sha256: dict[str, str] = Field(default_factory=dict)
    output_sha256: dict[str, str] = Field(default_factory=dict)
    config_sha256: str
    parent_checkpoint_sha256: str | None = None
    rollback_safe: bool = True
    created_at: float
    details: dict[str, Any] = Field(default_factory=dict)
    checkpoint_sha256: str


class RollbackPlan(BaseModel):
    job_id: str
    target_checkpoint_sha256: str
    target_stage: str
    invalidated_checkpoint_sha256: list[str] = Field(default_factory=list)
    invalidated_stages: list[str] = Field(default_factory=list)
    safe: bool
    blockers: list[str] = Field(default_factory=list)


def _digest(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str).encode('utf-8')).hexdigest()


def config_digest(config: dict[str, Any]) -> str:
    return _digest(config)


def compile_checkpoint(
    job_id: str,
    stage: str,
    attempt: int,
    status: CheckpointStatus,
    *,
    config: dict[str, Any],
    input_sha256: dict[str, str] | None = None,
    output_sha256: dict[str, str] | None = None,
    parent_checkpoint_sha256: str | None = None,
    rollback_safe: bool = True,
    created_at: float | None = None,
    details: dict[str, Any] | None = None,
) -> StageCheckpoint:
    base = {
        'schema_version': 'character3d-stage-checkpoint-v1',
        'job_id': job_id,
        'stage': stage,
        'attempt': attempt,
        'status': status,
        'input_sha256': dict(sorted((input_sha256 or {}).items())),
        'output_sha256': dict(sorted((output_sha256 or {}).items())),
        'config_sha256': config_digest(config),
        'parent_checkpoint_sha256': parent_checkpoint_sha256,
        'rollback_safe': rollback_safe,
        'created_at': float(time.time() if created_at is None else created_at),
        'details': details or {},
    }
    return StageCheckpoint(**base, checkpoint_sha256=_digest(base))


def verify_checkpoint(checkpoint: StageCheckpoint) -> bool:
    base = checkpoint.model_dump(mode='json', exclude={'checkpoint_sha256'})
    return _digest(base) == checkpoint.checkpoint_sha256


class StageCheckpointStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._init()

    @contextmanager
    def _conn(self):
        c = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        c.row_factory = sqlite3.Row
        try:
            yield c
        finally:
            c.close()

    def _init(self) -> None:
        with self._conn() as c:
            c.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS stage_checkpoints(
                    checkpoint_sha256 TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(job_id, stage, attempt)
                );
                CREATE INDEX IF NOT EXISTS idx_stage_checkpoints_job_created ON stage_checkpoints(job_id, created_at);
                """
            )

    def append(self, checkpoint: StageCheckpoint) -> StageCheckpoint:
        if not verify_checkpoint(checkpoint):
            raise ValueError('checkpoint digest verification failed')
        with self._conn() as c:
            c.execute('BEGIN IMMEDIATE')
            if checkpoint.parent_checkpoint_sha256 is not None:
                parent = c.execute(
                    'SELECT 1 FROM stage_checkpoints WHERE checkpoint_sha256=? AND job_id=?',
                    (checkpoint.parent_checkpoint_sha256, checkpoint.job_id),
                ).fetchone()
                if not parent:
                    c.execute('ROLLBACK')
                    raise ValueError('parent checkpoint is not present for this job')
            c.execute(
                'INSERT INTO stage_checkpoints(checkpoint_sha256,job_id,stage,attempt,created_at,payload_json) VALUES(?,?,?,?,?,?)',
                (
                    checkpoint.checkpoint_sha256, checkpoint.job_id, checkpoint.stage, checkpoint.attempt,
                    checkpoint.created_at, checkpoint.model_dump_json(),
                ),
            )
            c.execute('COMMIT')
        return checkpoint

    def chain(self, job_id: str) -> list[StageCheckpoint]:
        with self._conn() as c:
            rows = c.execute(
                'SELECT payload_json FROM stage_checkpoints WHERE job_id=? ORDER BY created_at, rowid',
                (job_id,),
            ).fetchall()
        return [StageCheckpoint.model_validate_json(r['payload_json']) for r in rows]

    def verify_chain(self, job_id: str) -> bool:
        chain = self.chain(job_id)
        previous: str | None = None
        for item in chain:
            if not verify_checkpoint(item):
                return False
            if item.parent_checkpoint_sha256 != previous:
                return False
            previous = item.checkpoint_sha256
        return True

    def latest(self, job_id: str) -> StageCheckpoint | None:
        chain = self.chain(job_id)
        return chain[-1] if chain else None

    def rollback_plan(self, job_id: str, target_checkpoint_sha256: str) -> RollbackPlan:
        chain = self.chain(job_id)
        idx = next((i for i, c in enumerate(chain) if c.checkpoint_sha256 == target_checkpoint_sha256), None)
        if idx is None:
            raise KeyError((job_id, target_checkpoint_sha256))
        target = chain[idx]
        later = chain[idx + 1:]
        blockers = []
        if not target.rollback_safe:
            blockers.append(f'Target stage {target.stage} is not marked rollback-safe.')
        unsafe_later = [c.stage for c in later if not c.rollback_safe]
        if unsafe_later:
            blockers.append('Rollback crosses non-reversible stages: ' + ', '.join(unsafe_later))
        return RollbackPlan(
            job_id=job_id,
            target_checkpoint_sha256=target.checkpoint_sha256,
            target_stage=target.stage,
            invalidated_checkpoint_sha256=[c.checkpoint_sha256 for c in later],
            invalidated_stages=[c.stage for c in later],
            safe=not blockers,
            blockers=blockers,
        )
