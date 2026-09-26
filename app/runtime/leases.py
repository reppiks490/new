from __future__ import annotations
import sqlite3, time, uuid
from contextlib import contextmanager
from pathlib import Path
from pydantic import BaseModel

class WorkerLease(BaseModel):
    worker_id: str
    owner_id: str
    token: str
    acquired_at: float
    heartbeat_at: float
    expires_at: float

class LeaseStore:
    def __init__(self,path: str | Path):
        self.path=str(path); self._init()
    @contextmanager
    def _conn(self):
        conn=sqlite3.connect(self.path,timeout=5,isolation_level=None)
        try:
            yield conn
        finally:
            conn.close()
    def _init(self):
        with self._conn() as c:
            c.execute('CREATE TABLE IF NOT EXISTS worker_leases(worker_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, token TEXT NOT NULL, acquired_at REAL NOT NULL, heartbeat_at REAL NOT NULL, expires_at REAL NOT NULL)')
    def acquire(self,worker_id: str,owner_id: str,ttl_seconds: float=30,now: float|None=None) -> WorkerLease:
        now=time.time() if now is None else now; token=uuid.uuid4().hex
        with self._conn() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT owner_id,token,acquired_at,heartbeat_at,expires_at FROM worker_leases WHERE worker_id=?',(worker_id,)).fetchone()
            if row and row[4]>now: raise RuntimeError(f'worker {worker_id} is already leased')
            c.execute('REPLACE INTO worker_leases VALUES(?,?,?,?,?,?)',(worker_id,owner_id,token,now,now,now+ttl_seconds)); c.execute('COMMIT')
        return WorkerLease(worker_id=worker_id,owner_id=owner_id,token=token,acquired_at=now,heartbeat_at=now,expires_at=now+ttl_seconds)
    def heartbeat(self,worker_id: str,token: str,ttl_seconds: float=30,now: float|None=None) -> WorkerLease:
        now=time.time() if now is None else now
        with self._conn() as c:
            c.execute('BEGIN IMMEDIATE'); row=c.execute('SELECT owner_id,token,acquired_at,expires_at FROM worker_leases WHERE worker_id=?',(worker_id,)).fetchone()
            if not row or row[1]!=token: c.execute('ROLLBACK'); raise RuntimeError('lease token mismatch or lease missing')
            if row[3] <= now: c.execute('ROLLBACK'); raise RuntimeError('lease expired')
            exp=now+ttl_seconds; c.execute('UPDATE worker_leases SET heartbeat_at=?,expires_at=? WHERE worker_id=?',(now,exp,worker_id)); c.execute('COMMIT')
        return WorkerLease(worker_id=worker_id,owner_id=row[0],token=token,acquired_at=row[2],heartbeat_at=now,expires_at=exp)
    def release(self,worker_id: str,token: str) -> bool:
        with self._conn() as c:
            cur=c.execute('DELETE FROM worker_leases WHERE worker_id=? AND token=?',(worker_id,token)); return cur.rowcount==1
    def reclaim_expired(self,now: float|None=None) -> int:
        now=time.time() if now is None else now
        with self._conn() as c:
            cur=c.execute('DELETE FROM worker_leases WHERE expires_at<=?',(now,)); return cur.rowcount
