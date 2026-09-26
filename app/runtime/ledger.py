from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from app.providers.execution import ProviderTaskSnapshot, RemoteAsset


class ProviderLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS provider_tasks (
                provider TEXT NOT NULL,
                task_id TEXT NOT NULL,
                status TEXT NOT NULL,
                progress INTEGER,
                raw_status TEXT,
                credits_consumed REAL,
                error TEXT,
                metadata_json TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (provider, task_id)
            );
            CREATE TABLE IF NOT EXISTS provider_assets (
                provider TEXT NOT NULL,
                task_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                url TEXT NOT NULL,
                format TEXT,
                sha256 TEXT,
                local_path TEXT,
                size_bytes INTEGER,
                created_at REAL NOT NULL,
                UNIQUE(provider, task_id, url)
            );
            """
        )
        self.conn.commit()

    def upsert_snapshot(self, snapshot: ProviderTaskSnapshot) -> None:
        self.conn.execute(
            """INSERT INTO provider_tasks(provider,task_id,status,progress,raw_status,credits_consumed,error,metadata_json,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)
               ON CONFLICT(provider,task_id) DO UPDATE SET status=excluded.status,progress=excluded.progress,raw_status=excluded.raw_status,credits_consumed=excluded.credits_consumed,error=excluded.error,metadata_json=excluded.metadata_json,updated_at=excluded.updated_at""",
            (snapshot.provider.value, snapshot.task_id, snapshot.status.value, snapshot.progress, snapshot.raw_status, snapshot.credits_consumed, snapshot.error, json.dumps(snapshot.metadata, sort_keys=True), time.time()),
        )
        for asset in snapshot.assets:
            self.record_asset(snapshot.provider.value, snapshot.task_id, asset)
        self.conn.commit()

    def record_asset(self, provider: str, task_id: str, asset: RemoteAsset) -> None:
        self.conn.execute(
            """INSERT INTO provider_assets(provider,task_id,kind,url,format,sha256,local_path,size_bytes,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)
               ON CONFLICT(provider,task_id,url) DO UPDATE SET kind=excluded.kind,format=excluded.format,sha256=COALESCE(excluded.sha256,provider_assets.sha256),local_path=COALESCE(excluded.local_path,provider_assets.local_path),size_bytes=COALESCE(excluded.size_bytes,provider_assets.size_bytes)""",
            (provider, task_id, asset.kind, asset.url, asset.format, asset.sha256, asset.local_path, asset.size_bytes, time.time()),
        )

    def get_task(self, provider: str, task_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM provider_tasks WHERE provider=? AND task_id=?", (provider, task_id)).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["metadata"] = json.loads(data.pop("metadata_json"))
        data["assets"] = [dict(r) for r in self.conn.execute("SELECT * FROM provider_assets WHERE provider=? AND task_id=? ORDER BY created_at", (provider, task_id))]
        return data

    def close(self) -> None:
        self.conn.close()
