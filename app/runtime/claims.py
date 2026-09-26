from __future__ import annotations

import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from pydantic import BaseModel


ClaimState = Literal["queued", "leased", "retry_wait", "succeeded", "failed"]


class JobClaim(BaseModel):
    job_id: str
    state: ClaimState
    owner_id: str | None = None
    token: str | None = None
    attempt: int = 0
    available_at: float
    lease_expires_at: float | None = None
    last_error: str | None = None


class JobClaimStore:
    """Durable at-most-one-active-owner job claiming with retry backoff.

    Claims are token-guarded. Expired leases can be reclaimed without incrementing the
    attempt counter until a new owner successfully claims the job.
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

    def _init(self):
        with self._conn() as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS job_claims(
                job_id TEXT PRIMARY KEY, state TEXT NOT NULL, owner_id TEXT, token TEXT,
                attempt INTEGER NOT NULL, available_at REAL NOT NULL, lease_expires_at REAL,
                last_error TEXT, updated_at REAL NOT NULL)"""
            )

    def enqueue(self, job_id: str, *, available_at: float | None = None) -> JobClaim:
        now = time.time()
        available = now if available_at is None else available_at
        with self._conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO job_claims(job_id,state,attempt,available_at,updated_at) VALUES(?,?,?,?,?)",
                (job_id, "queued", 0, available, now),
            )
        return self.get(job_id)

    def claim(self, job_id: str, owner_id: str, *, ttl_seconds: float = 60, now: float | None = None) -> JobClaim:
        now = time.time() if now is None else now
        token = uuid.uuid4().hex
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT * FROM job_claims WHERE job_id=?", (job_id,)).fetchone()
            if not row:
                c.execute("ROLLBACK")
                raise RuntimeError("job is not enqueued")
            state = row["state"]
            lease_exp = row["lease_expires_at"]
            if state == "leased" and lease_exp is not None and lease_exp > now:
                c.execute("ROLLBACK")
                raise RuntimeError("job already has an active owner")
            if state in {"succeeded", "failed"}:
                c.execute("ROLLBACK")
                raise RuntimeError(f"job is terminal: {state}")
            if row["available_at"] > now:
                c.execute("ROLLBACK")
                raise RuntimeError("job is waiting for retry backoff")
            attempt = int(row["attempt"]) + 1
            c.execute(
                "UPDATE job_claims SET state='leased',owner_id=?,token=?,attempt=?,lease_expires_at=?,updated_at=? WHERE job_id=?",
                (owner_id, token, attempt, now + ttl_seconds, now, job_id),
            )
            c.execute("COMMIT")
        return self.get(job_id)

    def heartbeat(self, job_id: str, token: str, *, ttl_seconds: float = 60, now: float | None = None) -> JobClaim:
        now = time.time() if now is None else now
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT * FROM job_claims WHERE job_id=?", (job_id,)).fetchone()
            if not row or row["state"] != "leased" or row["token"] != token:
                c.execute("ROLLBACK")
                raise RuntimeError("claim token mismatch or job is not leased")
            if row["lease_expires_at"] is not None and row["lease_expires_at"] <= now:
                c.execute("ROLLBACK")
                raise RuntimeError("claim lease expired")
            c.execute("UPDATE job_claims SET lease_expires_at=?,updated_at=? WHERE job_id=?", (now + ttl_seconds, now, job_id))
            c.execute("COMMIT")
        return self.get(job_id)

    def complete(self, job_id: str, token: str, *, now: float | None = None) -> JobClaim:
        return self._terminal(job_id, token, "succeeded", None, now)

    def fail(self, job_id: str, token: str, *, retryable: bool, error: str, retry_delay: float = 30, now: float | None = None) -> JobClaim:
        now = time.time() if now is None else now
        if retryable:
            with self._conn() as c:
                c.execute("BEGIN IMMEDIATE")
                row = c.execute("SELECT * FROM job_claims WHERE job_id=?", (job_id,)).fetchone()
                if not row or row["state"] != "leased" or row["token"] != token:
                    c.execute("ROLLBACK")
                    raise RuntimeError("claim token mismatch or job is not leased")
                c.execute(
                    "UPDATE job_claims SET state='retry_wait',owner_id=NULL,token=NULL,available_at=?,lease_expires_at=NULL,last_error=?,updated_at=? WHERE job_id=?",
                    (now + retry_delay, error, now, job_id),
                )
                c.execute("COMMIT")
            return self.get(job_id)
        return self._terminal(job_id, token, "failed", error, now)

    def _terminal(self, job_id: str, token: str, state: Literal["succeeded", "failed"], error: str | None, now: float | None) -> JobClaim:
        now = time.time() if now is None else now
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT * FROM job_claims WHERE job_id=?", (job_id,)).fetchone()
            if not row or row["state"] != "leased" or row["token"] != token:
                c.execute("ROLLBACK")
                raise RuntimeError("claim token mismatch or job is not leased")
            c.execute(
                "UPDATE job_claims SET state=?,owner_id=NULL,token=NULL,lease_expires_at=NULL,last_error=?,updated_at=? WHERE job_id=?",
                (state, error, now, job_id),
            )
            c.execute("COMMIT")
        return self.get(job_id)

    def get(self, job_id: str) -> JobClaim:
        with self._conn() as c:
            row = c.execute("SELECT * FROM job_claims WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            raise KeyError(job_id)
        return JobClaim(
            job_id=row["job_id"], state=row["state"], owner_id=row["owner_id"], token=row["token"],
            attempt=row["attempt"], available_at=row["available_at"], lease_expires_at=row["lease_expires_at"],
            last_error=row["last_error"],
        )
