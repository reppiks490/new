from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ArtifactVersion(BaseModel):
    asset_id: str
    version: int
    sha256: str
    stage: str
    parent_sha256: str | None = None
    path: str | None = None
    branch: str = 'main'
    created_at: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActiveArtifact(BaseModel):
    asset_id: str
    version: int
    sha256: str
    branch: str


class RollbackEvent(BaseModel):
    asset_id: str
    from_sha256: str | None
    to_sha256: str
    reason: str
    created_at: float


class ArtifactLineageStore:
    """Immutable artifact history with a mutable active pointer.

    Rollback never deletes or mutates historical versions; it only changes the active pointer
    and appends an audit event. Pointer changes support compare-and-swap to avoid lost updates.
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._init()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init(self) -> None:
        with self._conn() as c:
            c.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS artifact_versions(
                    asset_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    parent_sha256 TEXT,
                    path TEXT,
                    branch TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    metadata_json TEXT NOT NULL,
                    PRIMARY KEY(asset_id, version),
                    UNIQUE(asset_id, sha256, branch)
                );
                CREATE TABLE IF NOT EXISTS artifact_active(
                    asset_id TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS artifact_rollbacks(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id TEXT NOT NULL,
                    from_sha256 TEXT,
                    to_sha256 TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )

    def register(
        self,
        asset_id: str,
        sha256: str,
        stage: str,
        *,
        parent_sha256: str | None = None,
        path: str | None = None,
        branch: str = 'main',
        metadata: dict[str, Any] | None = None,
        activate: bool = True,
        created_at: float | None = None,
    ) -> ArtifactVersion:
        if len(sha256) != 64:
            raise ValueError('sha256 must be a 64-character hex digest')
        try:
            int(sha256, 16)
        except ValueError as exc:
            raise ValueError('sha256 must be hexadecimal') from exc
        now = time.time() if created_at is None else created_at
        meta_json = json.dumps(metadata or {}, sort_keys=True, separators=(',', ':'))
        with self._conn() as c:
            c.execute('BEGIN IMMEDIATE')
            if parent_sha256 is not None:
                parent = c.execute(
                    'SELECT 1 FROM artifact_versions WHERE asset_id=? AND sha256=?',
                    (asset_id, parent_sha256),
                ).fetchone()
                if not parent:
                    c.execute('ROLLBACK')
                    raise ValueError('parent_sha256 is not present in this asset lineage')
            existing = c.execute(
                'SELECT * FROM artifact_versions WHERE asset_id=? AND sha256=? AND branch=?',
                (asset_id, sha256, branch),
            ).fetchone()
            if existing:
                c.execute('ROLLBACK')
                return self._row_to_version(existing)
            next_version = int(c.execute(
                'SELECT COALESCE(MAX(version),0)+1 FROM artifact_versions WHERE asset_id=?',
                (asset_id,),
            ).fetchone()[0])
            c.execute(
                'INSERT INTO artifact_versions(asset_id,version,sha256,stage,parent_sha256,path,branch,created_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,?)',
                (asset_id, next_version, sha256, stage, parent_sha256, path, branch, now, meta_json),
            )
            if activate:
                c.execute(
                    """INSERT INTO artifact_active(asset_id,version,sha256,branch,updated_at) VALUES(?,?,?,?,?)
                       ON CONFLICT(asset_id) DO UPDATE SET version=excluded.version,sha256=excluded.sha256,branch=excluded.branch,updated_at=excluded.updated_at""",
                    (asset_id, next_version, sha256, branch, now),
                )
            c.execute('COMMIT')
        return self.get_version(asset_id, next_version)

    def history(self, asset_id: str) -> list[ArtifactVersion]:
        with self._conn() as c:
            rows = c.execute('SELECT * FROM artifact_versions WHERE asset_id=? ORDER BY version', (asset_id,)).fetchall()
        return [self._row_to_version(r) for r in rows]

    def get_version(self, asset_id: str, version: int) -> ArtifactVersion:
        with self._conn() as c:
            row = c.execute('SELECT * FROM artifact_versions WHERE asset_id=? AND version=?', (asset_id, version)).fetchone()
        if not row:
            raise KeyError((asset_id, version))
        return self._row_to_version(row)

    def current(self, asset_id: str) -> ActiveArtifact | None:
        with self._conn() as c:
            row = c.execute('SELECT * FROM artifact_active WHERE asset_id=?', (asset_id,)).fetchone()
        if not row:
            return None
        return ActiveArtifact(asset_id=row['asset_id'], version=row['version'], sha256=row['sha256'], branch=row['branch'])

    def set_active(self, asset_id: str, target_sha256: str, *, expected_current_sha256: str | None = None) -> ActiveArtifact:
        now = time.time()
        with self._conn() as c:
            c.execute('BEGIN IMMEDIATE')
            target = c.execute(
                'SELECT * FROM artifact_versions WHERE asset_id=? AND sha256=? ORDER BY version DESC LIMIT 1',
                (asset_id, target_sha256),
            ).fetchone()
            if not target:
                c.execute('ROLLBACK')
                raise KeyError((asset_id, target_sha256))
            current = c.execute('SELECT * FROM artifact_active WHERE asset_id=?', (asset_id,)).fetchone()
            if expected_current_sha256 is not None:
                actual = current['sha256'] if current else None
                if actual != expected_current_sha256:
                    c.execute('ROLLBACK')
                    raise RuntimeError('active artifact changed; compare-and-swap failed')
            c.execute(
                """INSERT INTO artifact_active(asset_id,version,sha256,branch,updated_at) VALUES(?,?,?,?,?)
                   ON CONFLICT(asset_id) DO UPDATE SET version=excluded.version,sha256=excluded.sha256,branch=excluded.branch,updated_at=excluded.updated_at""",
                (asset_id, target['version'], target['sha256'], target['branch'], now),
            )
            c.execute('COMMIT')
        return self.current(asset_id)  # type: ignore[return-value]

    def rollback(self, asset_id: str, target_sha256: str, *, reason: str, expected_current_sha256: str | None = None) -> RollbackEvent:
        before = self.current(asset_id)
        self.set_active(asset_id, target_sha256, expected_current_sha256=expected_current_sha256)
        event = RollbackEvent(
            asset_id=asset_id,
            from_sha256=before.sha256 if before else None,
            to_sha256=target_sha256,
            reason=reason,
            created_at=time.time(),
        )
        with self._conn() as c:
            c.execute(
                'INSERT INTO artifact_rollbacks(asset_id,from_sha256,to_sha256,reason,created_at) VALUES(?,?,?,?,?)',
                (event.asset_id, event.from_sha256, event.to_sha256, event.reason, event.created_at),
            )
        return event

    @staticmethod
    def _row_to_version(row: sqlite3.Row) -> ArtifactVersion:
        return ArtifactVersion(
            asset_id=row['asset_id'], version=row['version'], sha256=row['sha256'], stage=row['stage'],
            parent_sha256=row['parent_sha256'], path=row['path'], branch=row['branch'], created_at=row['created_at'],
            metadata=json.loads(row['metadata_json']),
        )
