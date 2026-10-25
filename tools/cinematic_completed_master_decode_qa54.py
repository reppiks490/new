"""Opt-in offline full-decode verification of completed cinematic master MP4s.

No inference, mutation, repair, media upload, or automatic deletion. Requires a
quiescent owner-selected workspace. Results contain only aggregate counts.
"""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
import stat
import subprocess

_ID = re.compile(r"^[a-f0-9]{32}$")


def inspect(workspace: Path, database: Path, *, timeout: int = 60) -> dict[str, int | bool]:
    """Fully decode each distinct ready master; report only sanitized counts.

    A verified decode is a local file property, not proof of source lineage,
    model quality, phone playback or 600-second timeline accuracy. Optional
    timeline frame attestation is reported separately from decodability.
    """
    if timeout < 1 or workspace.is_symlink() or database.is_symlink():
        raise ValueError("invalid audit configuration")
    workspace = workspace.resolve(strict=True)
    database = database.resolve(strict=True)
    if not workspace.is_dir() or not database.is_file() or not database.is_relative_to(workspace):
        raise ValueError("invalid audit workspace")
    media_dir = workspace / "video-assets"
    if media_dir.is_symlink() or not media_dir.is_dir():
        raise ValueError("invalid media directory")
    if not media_dir.resolve(strict=True).is_relative_to(workspace):
        raise ValueError("invalid media directory")

    ready_records = 0
    invalid_records = 0
    identifiers: set[str] = set()
    # A duplicate asset with inconsistent or missing timeline claims is
    # unattested, even if its H.264 frames can be decoded.
    timeline_claims: dict[str, set[int | None]] = {}
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=10)) as db:
        db.execute("PRAGMA query_only=ON")
        for (raw,) in db.execute("SELECT data FROM records WHERE kind='video_master'"):
            try:
                record = json.loads(raw)
            except (TypeError, ValueError):
                invalid_records += 1
                continue
            if not isinstance(record, dict) or record.get("status") != "ready":
                invalid_records += 1
                continue
            ready_records += 1
            identifier = record.get("asset_id")
            if not isinstance(identifier, str) or not _ID.fullmatch(identifier):
                invalid_records += 1
                continue
            identifiers.add(identifier)
            frames = record.get("timeline_frames")
            stored_probe = record.get("probe")
            if (type(frames) is int and frames > 0
                    and isinstance(stored_probe, dict)
                    and type(stored_probe.get("frame_count")) is int
                    and stored_probe["frame_count"] == frames):
                timeline_claims.setdefault(identifier, set()).add(frames)
            else:
                timeline_claims.setdefault(identifier, set()).add(None)

    missing_or_unsafe = 0
    failed_probe = 0
    failed_decode = 0
    timed_out = 0
    verified = 0
    timeline_attested = 0
    timeline_mismatches = 0
    for identifier in sorted(identifiers):
        path = media_dir / (identifier + ".mp4")
        try:
            metadata = path.lstat()
        except OSError:
            missing_or_unsafe += 1
            continue
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_size == 0:
            missing_or_unsafe += 1
            continue
        try:
            probe = subprocess.run([
                "ffprobe", "-v", "error", "-protocol_whitelist", "file",
                "-show_entries", "stream=codec_type,width,height:format=format_name,duration",
                "-of", "json", "-i", str(path),
            ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            timed_out += 1
            continue
        except OSError:
            failed_probe += 1
            continue
        if probe.returncode:
            failed_probe += 1
            continue
        try:
            details = json.loads(probe.stdout)
            streams = details.get("streams", [])
            container = details.get("format", {})
            valid = (
                isinstance(streams, list)
                and any(isinstance(s, dict) and s.get("codec_type") == "video"
                        and isinstance(s.get("width"), int) and s["width"] > 0
                        and isinstance(s.get("height"), int) and s["height"] > 0
                        for s in streams)
                and isinstance(container, dict)
                and "mp4" in str(container.get("format_name", "")).split(",")
                and float(container.get("duration", 0)) > 0
            )
        except (TypeError, ValueError, AttributeError, OverflowError):
            valid = False
        if not valid:
            failed_probe += 1
            continue
        try:
            decode = subprocess.run([
                "ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-xerror",
                "-protocol_whitelist", "file", "-progress", "pipe:1",
                "-i", str(path), "-map", "0:v:0", "-an",
                "-fps_mode", "passthrough", "-f", "null", "-",
            ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
               timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            timed_out += 1
            continue
        except OSError:
            failed_decode += 1
            continue
        if decode.returncode:
            failed_decode += 1
        else:
            verified += 1
            claims = timeline_claims.get(identifier, {None})
            if len(claims) == 1:
                claimed_frames = next(iter(claims))
                if claimed_frames is not None:
                    # FFmpeg's final progress block reports frames that actually
                    # traversed the decoder, unlike container header nb_frames.
                    lines = decode.stdout.decode("ascii", "replace").splitlines()
                    frame_lines = [line for line in lines if line.startswith("frame=")]
                    if "progress=end" in lines and frame_lines:
                        try:
                            decoded_frames = int(frame_lines[-1].split("=", 1)[1].strip())
                        except ValueError:
                            decoded_frames = None
                        if decoded_frames is not None:
                            if decoded_frames == claimed_frames:
                                timeline_attested += 1
                            else:
                                timeline_mismatches += 1

    unverified = len(identifiers) - verified
    timeline_unattested = len(identifiers) - timeline_attested
    return {
        "ready_master_records": ready_records,
        "unique_ready_assets": len(identifiers),
        "verified_decodable_masters": verified,
        "unverified_completed_masters": unverified,
        "timeline_attested_masters": timeline_attested,
        "timeline_unattested_masters": timeline_unattested,
        "timeline_frame_mismatch_count": timeline_mismatches,
        "timeline_attestation_complete": (
            bool(identifiers) and timeline_unattested == 0 and invalid_records == 0
        ),
        "failed_probe_count": failed_probe,
        "failed_decode_count": failed_decode,
        "missing_or_unsafe_count": missing_or_unsafe,
        "timed_out_count": timed_out,
        "malformed_or_invalid_records": invalid_records,
        "verification_complete": bool(identifiers) and unverified == 0 and invalid_records == 0,
        "safe_to_delete_automatically": False,
    }


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Offline private completed-master full-decode audit")
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    try:
        report = inspect(args.workspace, args.database, timeout=args.timeout)
    except (OSError, ValueError, sqlite3.Error):
        print('{"error":"audit_failed"}')
        return 2
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["verification_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
