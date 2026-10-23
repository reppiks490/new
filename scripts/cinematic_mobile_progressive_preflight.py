"""Read-only MP4 progressive-start acceptance for locally verified cinematic masters.

This optional QA gate extends the SHA/full-decode and H.264 4:2:0 gates from
QA17/QA18. It never changes media or uploads it. A faststart MP4 is only a
container prerequisite, not evidence of private HTTP Range or phone playback.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.cinematic_mobile_h264_preflight import (
    VerificationFailure,
    verify_mobile_h264,
)


def _scan_top_level_boxes(path: Path) -> None:
    """Require exactly one ftyp, moov and mdat, in progressive MP4 order.

    Seek past payloads rather than loading potentially 600-second media into
    memory. Check every atom's declared size against the physical file size.
    """
    try:
        length = path.stat().st_size
        positions: dict[bytes, list[int]] = {b'ftyp': [], b'moov': [], b'mdat': []}
        with path.open('rb') as source:
            offset = 0
            while offset < length:
                remaining = length - offset
                if remaining < 8:
                    raise VerificationFailure('mp4_atom_invalid')
                source.seek(offset)
                header = source.read(8)
                if len(header) != 8:
                    raise VerificationFailure('mp4_atom_invalid')
                atom_size = int.from_bytes(header[:4], 'big')
                atom_type = header[4:8]
                header_size = 8
                if atom_size == 1:
                    extended = source.read(8)
                    if len(extended) != 8:
                        raise VerificationFailure('mp4_atom_invalid')
                    atom_size = int.from_bytes(extended, 'big')
                    header_size = 16
                elif atom_size == 0:
                    atom_size = remaining
                if atom_size < header_size or atom_size > remaining:
                    raise VerificationFailure('mp4_atom_invalid')
                if atom_type in positions:
                    positions[atom_type].append(offset)
                if atom_type == b'moof':
                    raise VerificationFailure('mp4_fragmented_unsupported')
                offset += atom_size
        if not all(len(offsets) == 1 for offsets in positions.values()):
            raise VerificationFailure('mp4_atom_invalid')
        if not (positions[b'ftyp'][0] < positions[b'moov'][0] < positions[b'mdat'][0]):
            raise VerificationFailure('mp4_faststart_missing')
    except OSError as exc:
        raise VerificationFailure('mp4_atom_unreadable') from exc


def verify_mobile_progressive(
    path: Path, *, expected_sha256: str, fps: int, frames: int,
    width: int, height: int, ffprobe: str = 'ffprobe', ffmpeg: str = 'ffmpeg',
) -> dict:
    """Verify full media integrity, mobile H.264 format and faststart atoms.

    This does NOT verify AAC/audio, HTTP Range, network transport, real phone
    playback, local GPU inference, or the absence of post-check file mutation.
    """
    baseline = verify_mobile_h264(
        path, expected_sha256=expected_sha256, fps=fps, frames=frames,
        width=width, height=height, ffprobe=ffprobe, ffmpeg=ffmpeg,
    )
    _scan_top_level_boxes(path)
    return {
        **baseline,
        'mp4_faststart_verified': True,
        'private_http_range_verified': False,
        'owner_mobile_playback_verified': False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Read-only progressive MP4 mobile preflight')
    parser.add_argument('--mp4', type=Path, required=True)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--fps', type=int, required=True)
    parser.add_argument('--frames', type=int, required=True)
    parser.add_argument('--width', type=int, required=True)
    parser.add_argument('--height', type=int, required=True)
    parser.add_argument('--ffprobe', default='ffprobe')
    parser.add_argument('--ffmpeg', default='ffmpeg')
    args = parser.parse_args(argv)
    try:
        result = verify_mobile_progressive(
            args.mp4, expected_sha256=args.expected_sha256, fps=args.fps,
            frames=args.frames, width=args.width, height=args.height,
            ffprobe=args.ffprobe, ffmpeg=args.ffmpeg,
        )
    except VerificationFailure as exc:
        print(json.dumps({'verified': False, 'reason': exc.reason}))
        return 2
    except Exception:
        print(json.dumps({'verified': False, 'reason': 'verification_failed'}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
