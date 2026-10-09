from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid


def root():
    p = Path(os.getenv('CHARACTER3D_STUDIO_WORKSPACE', './workspace/studio')).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def asset_path(identifier: str, extension='glb') -> Path:
    if not re.fullmatch(r'[a-f0-9]{32}', identifier) or extension not in {'glb', 'png'}:
        raise ValueError('Invalid asset identifier')
    directory = root()/'assets'
    directory.mkdir(exist_ok=True)
    path = directory / f'{identifier}.{extension}'
    if not path.resolve().is_relative_to(directory.resolve()) or path.is_symlink():
        raise ValueError('Asset escapes workspace')
    return path


@contextmanager
def connection():
    db = sqlite3.connect(root()/'studio.sqlite', timeout=10)
    try:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, kind TEXT, data TEXT, updated REAL)')
        with db:
            yield db
    finally:
        # sqlite's own context manager commits/rolls back but does not close.
        db.close()


def put(kind, data, identifier=None):
    identifier = identifier or uuid.uuid4().hex
    if not re.fullmatch(r'[a-f0-9]{32}', identifier):
        raise ValueError('Invalid record identifier')
    with connection() as db:
        db.execute('INSERT INTO records VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated=excluded.updated',
                   (identifier, kind, json.dumps(data, allow_nan=False), time.time()))
    return {'id': identifier, **data}


def get(kind, identifier):
    with connection() as db:
        row = db.execute('SELECT data FROM records WHERE kind=? AND id=?', (kind, identifier)).fetchone()
    if row is None:
        raise KeyError(identifier)
    return {'id': identifier, **json.loads(row[0])}


def list_records(kind):
    with connection() as db:
        rows = db.execute('SELECT id,data FROM records WHERE kind=? ORDER BY updated DESC LIMIT 100', (kind,)).fetchall()
    return [{'id': i, **json.loads(d)} for i,d in rows]


class JobCapacityError(RuntimeError):
    pass


def enqueue_job(data, *, max_active=4):
    """Reserve capacity and persist a job in one cross-process transaction."""
    identifier = uuid.uuid4().hex
    value = {**data, 'status': 'queued', 'stage': 'Queued'}
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        active = db.execute(
            "SELECT COUNT(*) FROM records WHERE kind='job' "
            "AND json_extract(data, '$.status') IN ('queued', 'running')"
        ).fetchone()[0]
        if active >= max_active:
            raise JobCapacityError(f'{max_active} generation jobs are already active')
        db.execute('INSERT INTO records VALUES(?,?,?,?)',
                   (identifier, 'job', json.dumps(value, allow_nan=False), time.time()))
    return {'id': identifier, **value}


def interrupt_active_jobs():
    """Recover every unfinished job, including those outside the UI's latest 100."""
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        rows = db.execute(
            "SELECT id,data FROM records WHERE kind='job' "
            "AND json_extract(data, '$.status') IN ('queued', 'running')"
        ).fetchall()
        for identifier, raw in rows:
            value = {**json.loads(raw), 'status': 'failed', 'stage': 'Interrupted',
                     'error': 'Worker restarted. Inspect recorded remote task IDs before submitting again.'}
            db.execute('UPDATE records SET data=?, updated=? WHERE id=?',
                       (json.dumps(value, allow_nan=False), time.time(), identifier))
    return len(rows)
