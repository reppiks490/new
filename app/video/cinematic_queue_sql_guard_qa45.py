"""Opt-in SQLite query candidate for malformed cinematic master queue rows.

This module is NOT wired into the production worker. It supplies exact SQL
replacements for the six read sites in cinematic_assembly_jobs.py so the lead
can integrate them atomically with queue admission, claim and recovery tests.

SQLite may reorder WHERE predicates: `kind=? AND json_valid(data) AND
json_extract(...)` is not a reliable protection. The CASE expression prevents
JSON extraction from evaluating on invalid JSON text. Invalid rows remain in
SQLite for private diagnostics; no mutation or logging occurs here.
"""
from __future__ import annotations

import sqlite3

_KIND = "video_assembly_job"
_STATUS = "CASE WHEN json_valid(data) = 1 THEN json_extract(data, '$.status') ELSE NULL END"
_PROJECT = "CASE WHEN json_valid(data) = 1 THEN json_extract(data, '$.project_id') ELSE NULL END"


def running_count(db: sqlite3.Connection) -> int:
    """Read-only single-flight guard; caller must hold BEGIN IMMEDIATE to claim."""
    return int(db.execute(
        f"SELECT COUNT(*) FROM records WHERE kind=? AND ({_STATUS})='running'",
        (_KIND,),
    ).fetchone()[0])


def next_queued(db: sqlite3.Connection) -> tuple[str, str] | None:
    """Oldest valid queued row; caller must check running_count first."""
    return db.execute(
        f"SELECT id,data FROM records WHERE kind=? AND ({_STATUS})='queued' "
        "ORDER BY updated ASC,id ASC LIMIT 1",
        (_KIND,),
    ).fetchone()


def running_rows_for_recovery(db: sqlite3.Connection) -> list[tuple[str, str]]:
    """Only valid-JSON running records; caller owns fenced recovery writes."""
    return db.execute(
        f"SELECT id,data FROM records WHERE kind=? AND ({_STATUS})='running'",
        (_KIND,),
    ).fetchall()


def active_project_rows(db: sqlite3.Connection, project_id: str) -> list[tuple[str, str]]:
    """Candidate for the active-project idempotency lookup."""
    return db.execute(
        f"SELECT id,data FROM records WHERE kind=? AND ({_PROJECT})=? "
        f"AND ({_STATUS}) IN ('queued','running')",
        (_KIND, project_id),
    ).fetchall()


def outstanding_count(db: sqlite3.Connection) -> int:
    """Preserves 32-slot capacity accounting for valid active rows."""
    return int(db.execute(
        f"SELECT COUNT(*) FROM records WHERE kind=? "
        f"AND ({_STATUS}) IN ('queued','running')",
        (_KIND,),
    ).fetchone()[0])


def project_history_page(
    db: sqlite3.Connection, project_id: str, *, limit: int = 50, offset: int = 0,
) -> tuple[int, list[tuple[str, str]]]:
    """Project-scoped history, excluding invalid JSON without exposing it."""
    if type(limit) is not int or type(offset) is not int or not 1 <= limit <= 200 or offset < 0:
        raise ValueError("limit must be 1..200 and offset nonnegative")
    total = int(db.execute(
        f"SELECT COUNT(*) FROM records WHERE kind=? AND ({_PROJECT})=?",
        (_KIND, project_id),
    ).fetchone()[0])
    rows = db.execute(
        f"SELECT id,data FROM records WHERE kind=? AND ({_PROJECT})=? "
        "ORDER BY updated DESC,id DESC LIMIT ? OFFSET ?",
        (_KIND, project_id, limit, offset),
    ).fetchall()
    return total, rows
