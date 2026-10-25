"""Opt-in offline full-decode verification of completed cinematic master MP4s.

No inference, mutation, repair, media upload, or automatic deletion. Requires a
quiescent owner-selected workspace. Results contain only aggregate counts.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import tempfile

_ID = re.compile(r"^[a-f0-9]{32}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


def _pts_cadence(path: Path, frames: int, fps: int, timeout: int) -> bool | None:
    """Verify every presentation timestamp, independently of decoded frame parity.

    None means timing evidence unavailable; False means an actual mismatch.
    This checks video presentation cadence AND each frame's display duration,
    including the last frame. It does not check audio synchronization.
    Read-only FFprobe; no owner paths, metadata or stderr in the report.
    """
    try:
        probe = subprocess.run([
            "ffprobe", "-v", "error", "-protocol_whitelist", "file",
            "-select_streams", "v:0", "-show_frames",
            "-show_entries", "frame=best_effort_timestamp_time,duration_time,pkt_duration_time",
            "-of", "json", "-i", str(path),
        ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
           timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    # 600 s * 120 fps is ~72k frames; refuse unexpectedly huge output.
    if probe.returncode or len(probe.stdout) > 16 * 1024 * 1024:
        return None
    try:
        data = json.loads(probe.stdout)
        entries = data["frames"]
        if not isinstance(entries, list):
            return None
        if len(entries) != frames:
            return False
        expected_step = 1.0 / fps
        tolerance = min(0.002, expected_step / 8)
        previous = None
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                return None
            stamp = float(entry["best_effort_timestamp_time"])
            if not math.isfinite(stamp):
                return None
            # FFprobe uses duration_time on newer builds and
            # pkt_duration_time on older ones. Without a frame duration,
            # especially the last packet's, a PTS-only pass is not proof
            # of total presentation length: report unattested instead.
            raw_duration = entry.get("duration_time")
            if raw_duration is None:
                raw_duration = entry.get("pkt_duration_time")
            if raw_duration is None:
                return None
            duration = float(raw_duration)
            if not math.isfinite(duration):
                return None
            if duration <= 0 or abs(duration - expected_step) > tolerance:
                return False
            if abs(stamp - index * expected_step) > tolerance:
                return False
            if previous is not None and abs((stamp - previous) - expected_step) > tolerance:
                return False
            previous = stamp
        return bool(entries)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None



def _stable_file_sha256(path: Path, original: os.stat_result) -> str | None:
    """Hash only a stable regular single-link file; never report its bytes/path.

    Quiescence is still required: this is not an atomic multi-process snapshot.
    """
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                return None
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
            after = os.fstat(handle.fileno())
        current = path.lstat()
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_nlink")
        if any(
            getattr(original, field) != getattr(before, field)
            or getattr(before, field) != getattr(after, field)
            or getattr(after, field) != getattr(current, field)
            for field in fields
        ):
            return None
        return digest
    except OSError:
        return None



def _audio_timeline_matches(stream: dict, claim: tuple[int, int] | None) -> bool | None:
    """Check optional audio coverage against the persisted video delivery timeline.

    Audio absence is allowed and handled by the caller. This checks only
    stream start/end metadata, NOT decoded audio quality or lip synchronization.
    Missing/nonfinite evidence is unattested, not automatically corrupt.
    """
    if claim is None:
        return None
    try:
        start = float(stream["start_time"])
        duration = float(stream["duration"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(start) or not math.isfinite(duration) or duration <= 0:
        return None
    frames, fps = claim
    tolerance = max(0.01, 1.0 / fps)
    return abs(start) <= tolerance and abs(start + duration - frames / fps) <= tolerance


def _container_duration_matches(container: dict, frames: int, fps: int) -> bool | None:
    """Attest MP4 playback length, not just the decoded video frame cadence.

    A second stream or an MP4 edit list can extend the container beyond the
    valid video timeline. Missing/nonfinite duration evidence is unattested.
    Allow at most one frame of muxer rounding; no audio-sync claim is made.
    """
    try:
        duration = float(container["duration"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(duration) or duration <= 0:
        return None
    expected = frames / fps
    return abs(duration - expected) <= max(0.01, 1.0 / fps)


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
    timing_claims: dict[str, set[tuple[int, int] | None]] = {}
    hash_claims: dict[str, set[str | None]] = {}
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
            stored_hash = record.get("sha256")
            hash_claims.setdefault(identifier, set()).add(
                stored_hash if isinstance(stored_hash, str) and _SHA256.fullmatch(stored_hash)
                else None
            )
            frames = record.get("timeline_frames")
            stored_probe = record.get("probe")
            if (type(frames) is int and frames > 0
                    and isinstance(stored_probe, dict)
                    and type(stored_probe.get("frame_count")) is int
                    and stored_probe["frame_count"] == frames):
                timeline_claims.setdefault(identifier, set()).add(frames)
            else:
                timeline_claims.setdefault(identifier, set()).add(None)
            fps = record.get("delivery_fps")
            if (type(frames) is int and frames > 0
                    and isinstance(stored_probe, dict)
                    and type(stored_probe.get("frame_count")) is int
                    and stored_probe["frame_count"] == frames
                    and type(fps) is int and 1 <= fps <= 240):
                timing_claims.setdefault(identifier, set()).add((frames, fps))
            else:
                timing_claims.setdefault(identifier, set()).add(None)

    missing_or_unsafe = 0
    failed_probe = 0
    failed_decode = 0
    timed_out = 0
    verified = 0
    timeline_attested = 0
    timeline_mismatches = 0
    timing_attested = 0
    timing_anomalies = 0
    hash_attested = 0
    hash_mismatches = 0
    video_stream_anomalies = 0
    audio_stream_anomalies = 0
    audio_codec_anomalies = 0
    audio_codec_unattested = 0
    audio_timing_anomalies = 0
    audio_timing_unattested = 0
    audio_decode_anomalies = 0
    audio_decode_unattested = 0
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
                "-show_entries", "stream=codec_type,codec_name,profile,width,height,start_time,duration:format=format_name,duration",
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
        # The strict delivery contract is a single unambiguous video track.
        # Decode/timing checks intentionally select v:0, so extra video
        # streams could otherwise escape inspection and alter phone playback.
        # Preserve decode-only compatibility; gate only strict attestation.
        if sum(
            isinstance(stream, dict) and stream.get("codec_type") == "video"
            for stream in streams
        ) != 1:
            video_stream_anomalies += 1
        # Audio is optional, but a present soundtrack must cover the claimed
        # timeline from its start, with one unambiguous selectable audio track.
        # A short/late AAC stream can leave the MP4 container at 2s because
        # video still spans 2s, defeating container-duration-only checks.
        audio_streams = [
            stream for stream in streams
            if isinstance(stream, dict) and stream.get("codec_type") == "audio"
        ]
        if len(audio_streams) > 1:
            audio_stream_anomalies += 1
        elif len(audio_streams) == 1:
            # Mobile-delivery acceptance is AAC-LC when audio is present.
            # MP3 can be muxed into MP4 with valid timing and video/SHA,
            # but that is not the AAC-LC delivery contract. Missing codec
            # evidence is unattested, not a fabricated codec mismatch.
            codec = audio_streams[0].get("codec_name")
            profile = audio_streams[0].get("profile")
            if not isinstance(codec, str):
                audio_codec_unattested += 1
            elif codec != "aac":
                # A known non-AAC codec is anomalous even if that codec
                # has no meaningful FFprobe AAC profile field.
                audio_codec_anomalies += 1
            elif not isinstance(profile, str):
                audio_codec_unattested += 1
            elif profile != "LC":
                audio_codec_anomalies += 1
            timing = timing_claims.get(identifier, {None})
            claim = next(iter(timing)) if len(timing) == 1 else None
            audio_match = _audio_timeline_matches(audio_streams[0], claim)
            if audio_match is False:
                audio_timing_anomalies += 1
            elif audio_match is None:
                audio_timing_unattested += 1
            # FFprobe's codec/profile/start/duration metadata cannot prove
            # the AAC payload decodes. Some FFmpeg builds conceal damaged
            # packets and exit 0 while logging decoder errors at -v error.
            # Use an unnamed private temporary stream for bounded-memory
            # error observation; never publish stderr, paths or audio bytes.
            try:
                with tempfile.TemporaryFile(mode="w+b") as audio_errors:
                    audio_decode = subprocess.run([
                        "ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-xerror",
                        "-protocol_whitelist", "file", "-i", str(path),
                        "-map", "0:a:0", "-vn", "-f", "null", "-",
                    ], stdout=subprocess.DEVNULL, stderr=audio_errors,
                       timeout=timeout, check=False)
                    audio_errors.seek(0)
                    if audio_decode.returncode or audio_errors.read(1):
                        audio_decode_anomalies += 1
            except (OSError, subprocess.TimeoutExpired):
                audio_decode_unattested += 1
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
            stored_hashes = hash_claims.get(identifier, {None})
            if len(stored_hashes) == 1:
                stored_hash = next(iter(stored_hashes))
                if stored_hash is not None:
                    actual_hash = _stable_file_sha256(path, metadata)
                    if actual_hash is not None:
                        if actual_hash == stored_hash:
                            hash_attested += 1
                        else:
                            hash_mismatches += 1
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
                                timing = timing_claims.get(identifier, {None})
                                if len(timing) == 1:
                                    timing_claim = next(iter(timing))
                                    if timing_claim is not None and timing_claim[0] == claimed_frames:
                                        cadence = _pts_cadence(
                                            path, timing_claim[0], timing_claim[1], timeout
                                        )
                                        if cadence is True:
                                            # Frame PTS/durations can all be valid
                                            # while a longer audio/data stream
                                            # extends overall MP4 playback.
                                            container_match = _container_duration_matches(
                                                container, timing_claim[0], timing_claim[1]
                                            )
                                            if container_match is True:
                                                timing_attested += 1
                                            elif container_match is False:
                                                timing_anomalies += 1
                                        elif cadence is False:
                                            timing_anomalies += 1
                            else:
                                timeline_mismatches += 1

    unverified = len(identifiers) - verified
    timeline_unattested = len(identifiers) - timeline_attested
    timing_unattested = len(identifiers) - timing_attested
    hash_unattested = len(identifiers) - hash_attested
    return {
        "ready_master_records": ready_records,
        "unique_ready_assets": len(identifiers),
        "verified_decodable_masters": verified,
        "unverified_completed_masters": unverified,
        "timeline_attested_masters": timeline_attested,
        "timeline_unattested_masters": timeline_unattested,
        "timeline_frame_mismatch_count": timeline_mismatches,
        "timing_attested_masters": timing_attested,
        "timing_unattested_masters": timing_unattested,
        "timing_anomaly_count": timing_anomalies,
        "video_stream_anomaly_count": video_stream_anomalies,
        "audio_stream_anomaly_count": audio_stream_anomalies,
        "audio_codec_anomaly_count": audio_codec_anomalies,
        "audio_codec_unattested_count": audio_codec_unattested,
        "audio_timing_anomaly_count": audio_timing_anomalies,
        "audio_timing_unattested_count": audio_timing_unattested,
        "audio_decode_anomaly_count": audio_decode_anomalies,
        "audio_decode_unattested_count": audio_decode_unattested,
        "hash_attested_masters": hash_attested,
        "hash_unattested_masters": hash_unattested,
        "hash_mismatch_count": hash_mismatches,
        "hash_attestation_complete": (
            bool(identifiers) and hash_unattested == 0 and invalid_records == 0
        ),
        "timing_attestation_complete": (
            bool(identifiers) and timing_unattested == 0 and invalid_records == 0
        ),
        "timeline_attestation_complete": (
            bool(identifiers) and timeline_unattested == 0 and invalid_records == 0
        ),
        "failed_probe_count": failed_probe,
        "failed_decode_count": failed_decode,
        "missing_or_unsafe_count": missing_or_unsafe,
        "timed_out_count": timed_out,
        "malformed_or_invalid_records": invalid_records,
        "integrity_attestation_complete": (
            bool(identifiers) and invalid_records == 0 and unverified == 0
            and timeline_unattested == 0 and timing_unattested == 0
            and hash_unattested == 0 and video_stream_anomalies == 0
            and audio_stream_anomalies == 0 and audio_codec_anomalies == 0
            and audio_codec_unattested == 0 and audio_timing_anomalies == 0
            and audio_timing_unattested == 0
            and audio_decode_anomalies == 0 and audio_decode_unattested == 0
        ),
        "verification_complete": bool(identifiers) and unverified == 0 and invalid_records == 0,
        "safe_to_delete_automatically": False,
    }


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Offline private completed-master full-decode audit")
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument(
        "--require-integrity", action="store_true",
        help="Fail closed unless every completed master has decode, frame, timing and SHA attestation",
    )
    args = parser.parse_args()
    try:
        report = inspect(args.workspace, args.database, timeout=args.timeout)
    except (OSError, ValueError, sqlite3.Error):
        print('{"error":"audit_failed"}')
        return 2
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    passed = (report["integrity_attestation_complete"] if args.require_integrity
              else report["verification_complete"])
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
