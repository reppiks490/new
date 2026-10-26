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


_SAFE_FORMAT_TAGS = frozenset({
    "major_brand", "minor_version", "compatible_brands", "encoder",
})
_SAFE_STREAM_TAGS = frozenset({
    "language", "handler_name", "vendor_id", "encoder",
})
# FFmpeg writes an encoder tag by default, but the MP4 muxer also accepts an
# arbitrary user-supplied value for the SAME structural key. Checking keys
# alone therefore permits private prompt/identity text to be embedded in an
# otherwise valid master. Allow only known FFmpeg version + codec identities;
# unknown encoders are conservatively unattested by the strict privacy gate.
_SAFE_ENCODER_NAMES = frozenset({
    "libx264", "h264", "h264_nvenc", "h264_qsv", "h264_amf",
    "h264_vaapi", "h264_videotoolbox", "h264_mf",
    "aac", "libfdk_aac", "libmp3lame", "mpeg4", "libx265",
    "hevc", "hevc_nvenc", "libvpx", "libvpx-vp9",
})


def _expected_encoder_tag(value: object, *, format_tag: bool) -> bool:
    if not isinstance(value, str):
        return False
    if format_tag:
        return re.fullmatch(r"Lavf[0-9]+\.[0-9]+\.[0-9]+", value) is not None
    match = re.fullmatch(r"Lavc[0-9]+\.[0-9]+\.[0-9]+ ([A-Za-z0-9_.+-]+)", value)
    return match is not None and match.group(1) in _SAFE_ENCODER_NAMES


def _opaque_mp4_top_level_payload_present(
    path: Path, original: os.stat_result
) -> bool | None:
    """Check a narrow FFmpeg-master top-level ISO-BMFF box contract.

    FFprobe's stream/tag/chapter inventory ignores arbitrary top-level 'free'
    and 'uuid' payloads. A matching persisted SHA therefore cannot establish
    absence of private text in such boxes. Walk box headers only (constant
    memory), accept one ftyp/moov/mdat and only empty 'free' padding. Unknown
    boxes, nonempty padding, malformed lengths and duplicate core boxes fail
    strict acceptance. This does NOT inspect nested atoms or encoded pixels.
    Return None on filesystem uncertainty; never expose box bytes or paths.
    """
    required = {b"ftyp", b"moov", b"mdat"}
    allowed = required | {b"free"}
    seen: dict[bytes, int] = {}
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                != (original.st_dev, original.st_ino, original.st_size, original.st_mtime_ns)
            ):
                return None
            position = 0
            count = 0
            while position < before.st_size:
                count += 1
                if count > 4096 or before.st_size - position < 8:
                    return True
                handle.seek(position)
                header = handle.read(8)
                if len(header) != 8:
                    return None
                length = int.from_bytes(header[:4], "big")
                kind = header[4:8]
                header_length = 8
                if length == 1:
                    extended = handle.read(8)
                    if len(extended) != 8:
                        return None
                    length = int.from_bytes(extended, "big")
                    header_length = 16
                elif length == 0:
                    length = before.st_size - position
                if length < header_length or length > before.st_size - position:
                    return True
                if kind not in allowed or (kind == b"free" and length != header_length):
                    return True
                seen[kind] = seen.get(kind, 0) + 1
                if kind in required and seen[kind] != 1:
                    return True
                position += length
            after = os.fstat(handle.fileno())
            if (
                after.st_size != before.st_size
                or after.st_mtime_ns != before.st_mtime_ns
                or after.st_ino != before.st_ino
            ):
                return None
            return any(seen.get(kind) != 1 for kind in required)
    except OSError:
        return None



# Strict private-master delivery recognizes only known FFmpeg/ISO-BMFF
# structural children at the five inspected depths. FFprobe can silently
# ignore arbitrary other child box types containing owner-identifying text.
# This is a conservative *offline* contract, not a complete MP4 sanitizer.
_SAFE_NESTED_MP4_CHILDREN = {
    b"moov": frozenset({b"mvhd", b"trak", b"udta", b"meta", b"mvex", b"free"}),
    b"trak": frozenset({b"tkhd", b"edts", b"mdia", b"tref", b"free"}),
    b"mdia": frozenset({b"mdhd", b"hdlr", b"minf", b"elng", b"free"}),
    b"minf": frozenset({b"vmhd", b"smhd", b"hmhd", b"nmhd", b"dinf", b"stbl", b"free"}),
    b"stbl": frozenset({
        b"stsd", b"stts", b"ctts", b"stsc", b"stsz", b"stz2",
        b"stco", b"co64", b"stss", b"stsh", b"stdp", b"padb",
        b"sdtp", b"sgpd", b"sbgp", b"subs", b"saiz", b"saio", b"free",
    }),
    # FFmpeg's normal metadata and edit-list containers are allowed, but
    # arbitrary opaque children inside them must not escape strict auditing.
    b"udta": frozenset({b"meta", b"free"}),
    b"edts": frozenset({b"elst", b"free"}),
    # ISO-BMFF meta is a FullBox: skip its four version/flags bytes before
    # validating immediate children; arbitrary opaque siblings are not safe.
    b"meta": frozenset({b"hdlr", b"ilst", b"keys", b"free"}),
    # FFmpeg normally emits only the tool/encoder metadata item. Unknown
    # ilst items can hold private bytes without appearing in FFprobe tags.
    b"ilst": frozenset({b"\xa9too"}),
    # QA78: an otherwise allowed encoder item can hide an opaque sibling
    # beside its legitimate data child without surfacing in FFprobe tags.
    b"\xa9too": frozenset({b"data"}),
}


def _unexpected_nested_mp4_child(
    parent: bytes, kind: bytes, size: int, header_size: int
) -> bool:
    return kind not in _SAFE_NESTED_MP4_CHILDREN[parent] or (
        kind == b"free" and size != header_size
    )


def _opaque_mp4_moov_child_payload_present(
    path: Path, original: os.stat_result
) -> bool | None:
    """Reject opaque moov and immediate trak children in a narrow MP4 envelope.

    QA68 checks top-level boxes; QA69 checks immediate moov children; QA70
    checks immediate trak children; QA71 checks immediate mdia children; QA72 checks
    immediate minf children; QA73 checks immediate stbl children; QA75
    checks immediate udta/edts children.
    Scan bounded headers and reject unknown child types at these levels; never
    inspect encoded payloads or deeper descendants.
    False is a clean
    *narrow* check, NOT comprehensive MP4 sanitization. None means unstable
    file evidence.
    """
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            before = os.fstat(handle.fileno())
            fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_nlink")
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or any(getattr(before, key) != getattr(original, key) for key in fields)
            ):
                return None

            def header_at(position: int, limit: int) -> tuple[int | None, bytes | None, int | None]:
                if limit - position < 8:
                    return None, None, None
                handle.seek(position)
                header = handle.read(8)
                if len(header) != 8:
                    return None, None, None
                size = int.from_bytes(header[:4], "big")
                kind = header[4:8]
                header_size = 8
                if size == 1:
                    extra = handle.read(8)
                    if len(extra) != 8:
                        return None, None, None
                    size = int.from_bytes(extra, "big")
                    header_size = 16
                elif size == 0:
                    size = limit - position
                if size < header_size or size > limit - position:
                    return None, None, None
                return size, kind, header_size

            def allowed_container_children_clean(
                parent_kind: bytes, container_position: int,
                container_size: int, container_header_size: int
            ) -> bool:
                """Read bounded immediate child headers; never read payload bytes."""
                child_position = container_position + container_header_size
                child_limit = container_position + container_size
                encoder_data_children = 0
                for _ in range(4096):
                    if child_position >= child_limit:
                        break
                    child_size, child_kind, child_header_size = header_at(
                        child_position, child_limit
                    )
                    if child_size is None or _unexpected_nested_mp4_child(
                        parent_kind, child_kind, child_size, child_header_size
                    ):
                        return False
                    if child_kind == b"meta" and not meta_container_children_clean(
                        child_position, child_size, child_header_size
                    ):
                        return False
                    if parent_kind == b"\xa9too":
                        encoder_data_children += 1
                        if encoder_data_children > 1:
                            return False
                    if child_kind == b"ilst" and not allowed_container_children_clean(
                        b"ilst", child_position, child_size, child_header_size
                    ):
                        return False
                    if parent_kind == b"ilst" and child_kind == b"\xa9too" and not allowed_container_children_clean(
                        b"\xa9too", child_position, child_size, child_header_size
                    ):
                        return False
                    child_position += child_size
                # Reaching the iteration cap without reaching the end is NOT clean.
                return child_position == child_limit and (
                    parent_kind != b"\xa9too" or encoder_data_children == 1
                )

            def meta_container_children_clean(
                meta_position: int, meta_size: int, meta_header_size: int
            ) -> bool:
                # ISO-BMFF meta is a FullBox with four version/flags bytes.
                # Treat unexpected flags or truncated headers as unattested,
                # without copying or logging metadata payloads.
                if meta_size < meta_header_size + 4:
                    return False
                handle.seek(meta_position + meta_header_size)
                if handle.read(4) != bytes(4):
                    return False
                return allowed_container_children_clean(
                    b"meta", meta_position, meta_size, meta_header_size + 4
                )

            position = 0
            moov_position = None
            moov_size = None
            moov_header_size = None
            for _ in range(4096):
                if position >= before.st_size:
                    break
                size, kind, header_size = header_at(position, before.st_size)
                if size is None:
                    return True
                if kind == b"moov":
                    moov_position, moov_size, moov_header_size = position, size, header_size
                    break
                position += size
            if moov_position is None:
                return True

            position = moov_position + moov_header_size
            limit = moov_position + moov_size
            for _ in range(4096):
                if position >= limit:
                    break
                size, kind, header_size = header_at(position, limit)
                if size is None:
                    return True
                if _unexpected_nested_mp4_child(b"moov", kind, size, header_size):
                    return True
                if kind == b"meta" and not meta_container_children_clean(
                    position, size, header_size
                ):
                    return True
                if kind == b"udta" and not allowed_container_children_clean(
                    b"udta", position, size, header_size
                ):
                    return True
                if kind == b"trak":
                    # A valid track can hide opaque padding invisible to
                    # ffprobe's tags, stream inventory and full video decode.
                    # Scan immediate children only; never load their payloads.
                    track_position = position + header_size
                    track_limit = position + size
                    for _ in range(4096):
                        if track_position >= track_limit:
                            break
                        track_size, track_kind, track_header_size = header_at(
                            track_position, track_limit
                        )
                        if track_size is None:
                            return True
                        if _unexpected_nested_mp4_child(
                            b"trak", track_kind, track_size, track_header_size
                        ):
                            return True
                        if track_kind == b"edts" and not allowed_container_children_clean(
                            b"edts", track_position, track_size, track_header_size
                        ):
                            return True
                        if track_kind == b"mdia":
                            # FFprobe does not inventory opaque boxes inside
                            # the track media container. Read bounded headers
                            # only; never read, retain or report payload bytes.
                            media_position = track_position + track_header_size
                            media_limit = track_position + track_size
                            for _ in range(4096):
                                if media_position >= media_limit:
                                    break
                                media_size, media_kind, media_header_size = header_at(
                                    media_position, media_limit
                                )
                                if media_size is None:
                                    return True
                                if _unexpected_nested_mp4_child(
                                    b"mdia", media_kind, media_size, media_header_size
                                ):
                                    return True
                                if media_kind == b"minf":
                                    # FFprobe does not report opaque media-
                                    # information children. Traverse headers
                                    # only, bounded by the enclosing box.
                                    info_position = media_position + media_header_size
                                    info_limit = media_position + media_size
                                    for _ in range(4096):
                                        if info_position >= info_limit:
                                            break
                                        info_size, info_kind, info_header_size = header_at(
                                            info_position, info_limit
                                        )
                                        if info_size is None:
                                            return True
                                        if _unexpected_nested_mp4_child(
                                            b"minf", info_kind, info_size, info_header_size
                                        ):
                                            return True
                                        if info_kind == b"stbl":
                                            # Sample-table children can contain
                                            # opaque payloads invisible to FFprobe.
                                            # Read only bounded box headers.
                                            sample_position = info_position + info_header_size
                                            sample_limit = info_position + info_size
                                            for _ in range(4096):
                                                if sample_position >= sample_limit:
                                                    break
                                                sample_size, sample_kind, sample_header_size = header_at(
                                                    sample_position, sample_limit
                                                )
                                                if sample_size is None:
                                                    return True
                                                if _unexpected_nested_mp4_child(
                                                    b"stbl", sample_kind, sample_size,
                                                    sample_header_size,
                                                ):
                                                    return True
                                                sample_position += sample_size
                                            if sample_position != sample_limit:
                                                return True
                                        info_position += info_size
                                    if info_position != info_limit:
                                        return True
                                media_position += media_size
                            if media_position != media_limit:
                                return True
                        track_position += track_size
                    if track_position != track_limit:
                        return True
                position += size
            if position != limit:
                return True
            after = os.fstat(handle.fileno())
            current = path.lstat()
            if any(
                getattr(before, key) != getattr(after, key)
                or getattr(after, key) != getattr(current, key)
                for key in fields
            ):
                return None
            return False
    except OSError:
        return None


def _freeform_metadata_present(container: dict, streams: list) -> bool:
    """Conservatively flag unexpected FFprobe tag keys without emitting values.

    FFmpeg muxers normally add structural brand/encoder/handler tags. Arbitrary
    comment, title, description, location or user-defined tags are not part of
    the private delivery contract. This is NOT a complete MP4 box sanitizer.
    """
    for source, allowed in (
        [(container, _SAFE_FORMAT_TAGS)]
        + [(stream, _SAFE_STREAM_TAGS) for stream in streams
           if isinstance(stream, dict) and stream.get("codec_type") in ("video", "audio")]
    ):
        tags = source.get("tags", {})
        if not isinstance(tags, dict) or not tags.keys() <= allowed:
            return True
        handler = tags.get("handler_name")
        if handler is not None and handler not in (
            "VideoHandler", "SoundHandler", "AudioHandler"
        ):
            return True
        encoder = tags.get("encoder")
        if encoder is not None and not _expected_encoder_tag(
            encoder, format_tag=source is container
        ):
            return True
    return False


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
    auxiliary_stream_anomalies = 0
    freeform_metadata_anomalies = 0
    opaque_mp4_payload_anomalies = 0
    opaque_mp4_payload_unattested = 0
    nested_mp4_payload_anomalies = 0
    nested_mp4_payload_unattested = 0
    chapter_anomalies = 0
    chapter_unattested = 0
    video_codec_anomalies = 0
    video_codec_unattested = 0
    video_pixel_format_anomalies = 0
    video_pixel_format_unattested = 0
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
                "-show_entries", "stream=codec_type,codec_name,profile,pix_fmt,width,height,start_time,duration:stream_tags:format=format_name,duration:format_tags:chapter=start_time,end_time:chapter_tags",
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
        # Decodable H.264 frames and matching SHA do not imply private
        # delivery: subtitles/data streams, chapter titles and free-form
        # metadata can carry prompt or identity text. Only aggregate counters
        # are returned; never print FFprobe metadata values or file paths.
        if any(
            not isinstance(stream, dict)
            or stream.get("codec_type") not in ("video", "audio")
            for stream in streams
        ):
            auxiliary_stream_anomalies += 1
        if _freeform_metadata_present(container, streams):
            freeform_metadata_anomalies += 1
        # FFprobe omits arbitrary top-level 'free'/'uuid' box contents.
        # Validate a narrow private FFmpeg MP4 envelope without reading
        # or reporting opaque payload bytes; preserve decode-only behavior.
        opaque_payload = _opaque_mp4_top_level_payload_present(path, metadata)
        if opaque_payload is True:
            opaque_mp4_payload_anomalies += 1
        elif opaque_payload is None:
            opaque_mp4_payload_unattested += 1
        # Top-level boxes may be clean while a moov child carries opaque
        # private text. Inspect immediate children only, without publishing
        # bytes, filenames, hashes or other owner-identifying details.
        nested_payload = _opaque_mp4_moov_child_payload_present(path, metadata)
        if nested_payload is True:
            nested_mp4_payload_anomalies += 1
        elif nested_payload is None:
            nested_mp4_payload_unattested += 1
        chapters = details.get("chapters")
        if not isinstance(chapters, list):
            chapter_unattested += 1
        elif chapters:
            chapter_anomalies += 1
        # The strict delivery contract is a single unambiguous video track.
        # Decode/timing checks intentionally select v:0, so extra video
        # streams could otherwise escape inspection and alter phone playback.
        # Preserve decode-only compatibility; gate only strict attestation.
        video_streams = [
            stream for stream in streams
            if isinstance(stream, dict) and stream.get("codec_type") == "video"
        ]
        if len(video_streams) != 1:
            video_stream_anomalies += 1
        else:
            # A fully decodable, timestamp-correct MP4 is not necessarily
            # an H.264 8-bit 4:2:0 mobile-delivery master. MPEG-4 Part 2 and
            # H.264 4:4:4 can both satisfy all previous strict checks.
            # Missing FFprobe evidence is unattested, not fabricated damage.
            codec = video_streams[0].get("codec_name")
            if not isinstance(codec, str):
                video_codec_unattested += 1
            elif codec != "h264":
                video_codec_anomalies += 1
            pixel_format = video_streams[0].get("pix_fmt")
            if not isinstance(pixel_format, str):
                video_pixel_format_unattested += 1
            elif pixel_format != "yuv420p":
                video_pixel_format_anomalies += 1
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
        "auxiliary_stream_anomaly_count": auxiliary_stream_anomalies,
        "freeform_metadata_anomaly_count": freeform_metadata_anomalies,
        "opaque_mp4_payload_anomaly_count": opaque_mp4_payload_anomalies,
        "opaque_mp4_payload_unattested_count": opaque_mp4_payload_unattested,
        "nested_mp4_payload_anomaly_count": nested_mp4_payload_anomalies,
        "nested_mp4_payload_unattested_count": nested_mp4_payload_unattested,
        "chapter_anomaly_count": chapter_anomalies,
        "chapter_unattested_count": chapter_unattested,
        "video_codec_anomaly_count": video_codec_anomalies,
        "video_codec_unattested_count": video_codec_unattested,
        "video_pixel_format_anomaly_count": video_pixel_format_anomalies,
        "video_pixel_format_unattested_count": video_pixel_format_unattested,
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
            and auxiliary_stream_anomalies == 0
            and freeform_metadata_anomalies == 0
            and opaque_mp4_payload_anomalies == 0
            and opaque_mp4_payload_unattested == 0
            and nested_mp4_payload_anomalies == 0
            and nested_mp4_payload_unattested == 0
            and chapter_anomalies == 0 and chapter_unattested == 0
            and video_codec_anomalies == 0 and video_codec_unattested == 0
            and video_pixel_format_anomalies == 0
            and video_pixel_format_unattested == 0
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
