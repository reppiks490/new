"""Opt-in, read-only Character3D master-queue payload shape audit.

Unlike status-only queue health, this checks whether active records contain the
minimum fields consumed by the worker. It never returns raw records, IDs,
media paths, screenplay text, credentials or FFmpeg command lines.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3

_KIND = "video_assembly_job"
_ACTIVE = frozenset({"queued", "running"})
_ID = re.compile(r"[a-f0-9]{32}\Z")


class QueueAuditError(RuntimeError):
    """Neutral diagnostic; the database location is intentionally omitted."""


def _active_shape_ok(data: dict) -> bool:
    return (
        isinstance(data.get("project_id"), str)
        and _ID.fullmatch(data["project_id"]) is not None
        and type(data.get("project_revision")) is int
        and data["project_revision"] > 0
        and isinstance(data.get("ffmpeg_path"), str)
        and bool(data["ffmpeg_path"].strip())
    )


def inspect_payloads(path: str | Path) -> dict:
    """Read a local SQLite database without modifying queue records.

    `mode=ro` and `query_only` constrain this connection; SQLite may still
    interact with WAL/SHM sidecars. No worker liveness is inferred.
    """
    counts = {
        "valid_active": 0,
        "invalid_queued_shape": 0,
        "invalid_running_shape": 0,
        "invalid_json": 0,
        "non_object_json": 0,
        "terminal_or_unrecognized": 0,
    }
    try:
        db_path = Path(path).resolve(strict=True)
        if not db_path.is_file():
            raise QueueAuditError("Local queue database unavailable")
        with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
            db.execute("PRAGMA query_only=ON")
            if db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='records'"
            ).fetchone() is None:
                raise QueueAuditError("Local queue schema unavailable")
            rows = db.execute("SELECT data FROM records WHERE kind=?", (_KIND,))
            for (raw,) in rows:
                try:
                    payload = json.loads(raw)
                except (TypeError, ValueError):
                    counts["invalid_json"] += 1
                    continue
                if not isinstance(payload, dict):
                    counts["non_object_json"] += 1
                    continue
                status = payload.get("status")
                if not isinstance(status, str) or status not in _ACTIVE:
                    counts["terminal_or_unrecognized"] += 1
                    continue
                if _active_shape_ok(payload):
                    counts["valid_active"] += 1
                else:
                    counts[f"invalid_{status}_shape"] += 1
    except QueueAuditError:
        raise
    except (OSError, ValueError, sqlite3.Error) as exc:
        raise QueueAuditError("Local queue database could not be inspected") from exc

    warnings = []
    if counts["invalid_running_shape"]:
        warnings.append("structurally_invalid_running_row_may_block_claims")
    if counts["invalid_queued_shape"]:
        warnings.append("structurally_invalid_queued_row_may_fail_after_claim")
    if counts["invalid_json"]:
        warnings.append("invalid_json_can_abort_production_sql")
    if counts["non_object_json"]:
        warnings.append("non_object_json_records_present")
    return {
        "kind": _KIND,
        "counts": counts,
        "warnings": warnings,
        "read_only": True,
        "worker_liveness_verified": False,
        "owner_media_verified": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Private offline master queue payload audit")
    parser.add_argument("--db", required=True, help="Local SQLite database path (never printed)")
    args = parser.parse_args(argv)
    try:
        result = inspect_payloads(args.db)
    except QueueAuditError:
        print(json.dumps({"error": "Queue payload audit unavailable"}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
