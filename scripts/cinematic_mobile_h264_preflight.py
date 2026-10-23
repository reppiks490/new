"""Offline, read-only mobile H.264 encoding preflight for verified local masters.

This is a narrower *format* acceptance than real iPhone/browser playback. It
requires the independent full-decode and trusted-SHA gate from QA17 first.
Never uploads, changes or emits paths, prompts, credentials or media bytes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.cinematic_master_acceptance import (
    VerificationFailure,
    _run,
    verify_master,
)

_MOBILE_PROFILES = frozenset({'Constrained Baseline', 'Baseline', 'Main', 'High'})


def verify_mobile_h264(
    path: Path, *, expected_sha256: str, fps: int, frames: int,
    width: int, height: int, ffprobe: str = 'ffprobe', ffmpeg: str = 'ffmpeg',
) -> dict:
    """Verify SHA, strict decode, then MP4/H.264 8-bit 4:2:0 compatibility.

    This does not prove the phone's hardware level limits, private HTTP range
    support, browser compatibility, audio support or owner-device playback.
    """
    # A real SHA and full-decode check must precede any positive compatibility
    # result. The expected hash comes from trusted persisted metadata.
    baseline = verify_master(
        path, expected_sha256=expected_sha256, fps=fps, frames=frames,
        width=width, height=height, ffprobe=ffprobe, ffmpeg=ffmpeg,
    )
    probe = _run([
        ffprobe, '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=codec_type,codec_name,profile,pix_fmt:format=format_name',
        '-of', 'json', str(path),
    ], 120)
    if probe.returncode != 0:
        raise VerificationFailure('mobile_probe_failed')
    try:
        info = json.loads(probe.stdout)
        stream = next(s for s in info['streams'] if s.get('codec_type') == 'video')
        profile = stream['profile']
        pix_fmt = stream['pix_fmt']
        codec = stream['codec_name']
        container_formats = info['format']['format_name'].split(',')
        if not all(isinstance(x, str) for x in (profile, pix_fmt, codec)):
            raise ValueError('invalid stream field')
    except (KeyError, ValueError, TypeError, StopIteration, IndexError) as exc:
        raise VerificationFailure('mobile_probe_invalid') from exc
    if (
        codec != 'h264' or pix_fmt != 'yuv420p'
        or profile not in _MOBILE_PROFILES or 'mp4' not in container_formats
    ):
        raise VerificationFailure('mobile_profile_unsupported')
    return {
        **baseline,
        'mobile_h264_8bit_420_verified': True,
        'owner_mobile_playback_verified': False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Read-only mobile H.264 master preflight')
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
        result = verify_mobile_h264(
            args.mp4, expected_sha256=args.expected_sha256,
            fps=args.fps, frames=args.frames, width=args.width, height=args.height,
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
