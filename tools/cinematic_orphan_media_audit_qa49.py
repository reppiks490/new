"""Offline, read-only, privacy-safe inventory of *candidate* untracked MP4 files.

A process killed during FFmpeg output can bypass the assembler's Python
exception cleanup. This utility never deletes, opens, probes, or hashes media.
It deliberately cannot distinguish an orphan from an in-progress encoder or
an intentionally retained, unregistered file. Run only against a quiescent,
explicitly selected local cinematic workspace; do not publish the raw DB.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3

_MP4 = re.compile(r"^[a-f0-9]{32}\.mp4$")
_ID = re.compile(r"^[a-f0-9]{32}$")
_COMPLETE = {"video_job": "succeeded", "video_master": "ready"}


def audit(workspace: Path, database: Path) -> dict[str, int | bool]:
    """Inspect all video_job/video_master rows (no history truncation).

    JSON is parsed in Python so one malformed row cannot abort the inventory.
    No database or media mutations, and no owner identifiers in the result.
    """
    if workspace.is_symlink() or database.is_symlink():
        raise ValueError("unsafe audit path")
    workspace = workspace.resolve(strict=True)
    database = database.resolve(strict=True)
    if not workspace.is_dir() or not database.is_file() or not database.is_relative_to(workspace):
        raise ValueError("invalid audit workspace")
    media_dir = workspace / "video-assets"
    if media_dir.is_symlink() or not media_dir.is_dir():
        raise ValueError("missing or unsafe video asset directory")
    if not media_dir.resolve(strict=True).is_relative_to(workspace):
        raise ValueError("unsafe video asset directory")

    referenced: set[str] = set()
    completed: set[str] = set()
    malformed = 0
    invalid_asset_ids = 0
    active_jobs = 0
    # URI mode=ro avoids the application's CREATE TABLE and WAL-setting writes.
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=10)) as db:
        db.execute("PRAGMA query_only=ON")
        rows = db.execute(
            "SELECT kind,data FROM records WHERE kind IN ('video_job','video_master')"
        )
        for kind, raw in rows:
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError):
                malformed += 1
                continue
            if not isinstance(payload, dict):
                malformed += 1
                continue
            status = payload.get("status")
            if kind == "video_job" and isinstance(status, str) and status in {"queued", "running"}:
                active_jobs += 1
            identifier = payload.get("asset_id")
            if identifier is None:
                continue  # Unfinished jobs may not yet have an output ID.
            if not isinstance(identifier, str) or not _ID.fullmatch(identifier):
                invalid_asset_ids += 1
                continue
            referenced.add(identifier)
            if status == _COMPLETE[kind]:
                completed.add(identifier)

    seen: set[str] = set()
    candidates = 0
    candidate_bytes = 0
    small_candidates = 0
    unsafe_entries = 0
    for entry in media_dir.iterdir():
        if not _MP4.fullmatch(entry.name):
            continue
        if entry.is_symlink():
            unsafe_entries += 1
            continue
        if not entry.is_file():
            unsafe_entries += 1
            continue
        identifier = entry.stem
        seen.add(identifier)
        if identifier not in referenced:
            candidates += 1
            size = entry.stat().st_size
            candidate_bytes += size
            if size < 128:
                small_candidates += 1

    return {
        "tracked_mp4_ids": len(referenced),
        "completed_mp4_ids": len(completed),
        "missing_completed_mp4_ids": len(completed - seen),
        "candidate_untracked_mp4_files": candidates,
        "candidate_untracked_bytes": candidate_bytes,
        "candidate_small_files_under_128_bytes": small_candidates,
        "active_video_jobs": active_jobs,
        "malformed_record_count": malformed,
        "invalid_asset_id_count": invalid_asset_ids,
        "unsafe_mp4_entries_skipped": unsafe_entries,
        "safe_to_delete_automatically": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline, read-only cinematic MP4 candidate inventory")
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--database", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = audit(args.workspace, args.database)
    except (OSError, ValueError, sqlite3.Error):
        # Never print exception text: it can contain private paths or SQL data.
        print('{"error":"audit_failed"}')
        return 2
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
