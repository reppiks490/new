"""Read-only, privacy-safe snapshot of Character3D's local master queue.

No application imports, worker dispatch, migration, recovery or FFmpeg execution.
This reports database state, NOT whether a worker process is alive.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3
import time

_KIND = "video_assembly_job"
_STATES = ("queued", "running", "succeeded", "failed", "cancelled")
_CAPACITY = 32  # Observed _MAX_OUTSTANDING in frozen cinematic lead #40.


class QueueHealthError(RuntimeError):
    """Public diagnostic without workspace, script or credential details."""


def inspect_queue(db_path: str | Path, *, now: float | None = None) -> dict:
    """Return only aggregate, nonidentifying queue statistics.

    SQLite mode=ro and query_only prevent writes through this connection.
    WAL sidecar access is SQLite-managed and may require directory access.
    """
    try:
        path = Path(db_path).resolve(strict=True)
        if not path.is_file():
            raise QueueHealthError("Studio database is unavailable")
        uri = path.as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=2)) as db:
            db.execute("PRAGMA query_only=ON")
            exists = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='records'"
            ).fetchone()
            if not exists:
                raise QueueHealthError("Studio queue schema is unavailable")
            rows = db.execute(
                "SELECT CASE WHEN json_valid(data) THEN "
                "json_extract(data, '$.status') ELSE NULL END, updated "
                "FROM records WHERE kind=?", (_KIND,)
            )
            counts = {state: 0 for state in _STATES}
            counts["unknown"] = 0
            oldest = {"queued": None, "running": None}
            invalid_timestamps = 0
            future_timestamps = 0
            timestamp = time.time() if now is None else float(now)
            if not math.isfinite(timestamp):
                raise QueueHealthError("Invalid inspection clock")
            for status, updated in rows:
                state = status if isinstance(status, str) and status in _STATES else "unknown"
                counts[state] += 1
                if state not in oldest:
                    continue
                if not isinstance(updated, (float, int)) or not math.isfinite(updated) or updated < 0:
                    invalid_timestamps += 1
                    continue
                if updated > timestamp:
                    future_timestamps += 1
                    continue
                if oldest[state] is None or updated < oldest[state]:
                    oldest[state] = updated
    except QueueHealthError:
        raise
    except (OSError, ValueError, sqlite3.Error) as exc:
        raise QueueHealthError("Studio database could not be read safely") from exc

    outstanding = counts["queued"] + counts["running"]
    warnings = []
    if counts["running"] > 1:
        warnings.append("multiple_running_records")
    if outstanding >= _CAPACITY:
        warnings.append("queue_at_or_over_capacity")
    if counts["unknown"]:
        warnings.append("unrecognized_status_records")
    if invalid_timestamps:
        warnings.append("invalid_active_timestamps")
    if future_timestamps:
        warnings.append("future_active_timestamps")
    return {
        "kind": "video_assembly_job",
        "counts": counts,
        "outstanding": outstanding,
        "capacity_reference": _CAPACITY,
        "oldest_queued_age_seconds": (
            round(timestamp - oldest["queued"], 3) if oldest["queued"] is not None else None
        ),
        "oldest_running_age_seconds": (
            round(timestamp - oldest["running"], 3) if oldest["running"] is not None else None
        ),
        "warnings": warnings,
        "worker_liveness_verified": False,
        "database_mutated": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline read-only cinematic master queue snapshot")
    parser.add_argument("--db", required=True, help="Path to local studio.sqlite (not printed)")
    args = parser.parse_args(argv)
    try:
        report = inspect_queue(args.db)
    except QueueHealthError:
        print(json.dumps({"error": "Queue snapshot unavailable", "database_mutated": False}))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
