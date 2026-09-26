from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from app.providers.execution import ProviderTaskSnapshot, RemoteAsset
from app.providers.models import ProviderId


class ProviderLedger:
    """Small durable SQLite ledger for provider task state, webhook deduplication and assets."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS provider_tasks (
                    provider TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    raw_status TEXT,
                    progress INTEGER,
                    error TEXT,
                    metadata_json TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(provider, task_id)
                );
                CREATE TABLE IF NOT EXISTS provider_assets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    provider_url TEXT NOT NULL,
                    local_path TEXT,
                    sha256 TEXT,
                    size_bytes INTEGER,
                    format TEXT,
                    added_at REAL NOT NULL,
                    UNIQUE(provider, task_id, kind, provider_url)
                );
                CREATE TABLE IF NOT EXISTS webhook_deliveries (
                    provider TEXT NOT NULL,
                    delivery_id TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    received_at REAL NOT NULL,
                    PRIMARY KEY(provider, delivery_id)
                );
                """
            )

    def upsert_snapshot(self, snapshot: ProviderTaskSnapshot) -> None:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO provider_tasks(provider, task_id, status, raw_status, progress, error, metadata_json, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, task_id) DO UPDATE SET
                    status=excluded.status,
                    raw_status=excluded.raw_status,
                    progress=excluded.progress,
                    error=excluded.error,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    snapshot.provider.value,
                    snapshot.task_id,
                    snapshot.status.value,
                    snapshot.raw_status,
                    snapshot.progress,
                    snapshot.error,
                    json.dumps(snapshot.metadata, sort_keys=True),
                    now,
                ),
            )
            for asset in snapshot.assets:
                self._record_asset_conn(conn, snapshot.provider, snapshot.task_id, asset, now)

    def record_asset(self, provider: ProviderId, task_id: str, asset: RemoteAsset) -> None:
        with self._connect() as conn:
            self._record_asset_conn(conn, provider, task_id, asset, time.time())

    @staticmethod
    def _record_asset_conn(conn: sqlite3.Connection, provider: ProviderId, task_id: str, asset: RemoteAsset, now: float) -> None:
        conn.execute(
            """
            INSERT INTO provider_assets(provider, task_id, kind, provider_url, local_path, sha256, size_bytes, format, added_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider, task_id, kind, provider_url) DO UPDATE SET
                local_path=COALESCE(excluded.local_path, provider_assets.local_path),
                sha256=COALESCE(excluded.sha256, provider_assets.sha256),
                size_bytes=COALESCE(excluded.size_bytes, provider_assets.size_bytes),
                format=COALESCE(excluded.format, provider_assets.format),
                added_at=excluded.added_at
            """,
            (
                provider.value,
                task_id,
                asset.kind,
                asset.url,
                asset.local_path,
                asset.sha256,
                asset.size_bytes,
                asset.format,
                now,
            ),
        )

    def record_delivery(self, provider: ProviderId, delivery_id: str, raw_body: bytes) -> bool:
        """Return True for first-seen deliveries and False for duplicates."""
        digest = hashlib.sha256(raw_body).hexdigest()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO webhook_deliveries(provider, delivery_id, payload_sha256, received_at) VALUES(?, ?, ?, ?)",
                (provider.value, delivery_id, digest, time.time()),
            )
            return cur.rowcount == 1

    def get_task(self, provider: ProviderId, task_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM provider_tasks WHERE provider=? AND task_id=?", (provider.value, task_id)
            ).fetchone()
            return dict(row) if row else None

    def list_assets(self, provider: ProviderId, task_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM provider_assets WHERE provider=? AND task_id=? ORDER BY id", (provider.value, task_id)
            ).fetchall()
            return [dict(r) for r in rows]
