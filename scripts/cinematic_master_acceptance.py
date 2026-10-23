"""Offline, read-only local master verification; no network or owner-media upload.

This verifies MP4 bytes/metadata/full decode, not generative-model inference,
visual continuity, native resolution, owner-PC performance or mobile playback.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
from fractions import Fraction
from pathlib import Path
import re
import subprocess


class VerificationFailure(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _run(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (FileNotFoundError, PermissionError, OSError) as exc:
        raise VerificationFailure('media_tool_unavailable') from exc
    except subprocess.TimeoutExpired as exc:
        raise VerificationFailure('media_tool_timeout') from exc


def verify_master(
    path: Path, *, expected_sha256: str, fps: int, frames: int,
    width: int, height: int, ffprobe: str = 'ffprobe', ffmpeg: str = 'ffmpeg',
) -> dict:
    """Require all expected facts, matching bytes, ffprobe and full FFmpeg decode.

    Return privacy-minimized metrics only. Never print or persist file paths,
    prompts, credentials, media, subprocess output or frame contents.
    """
    if (
        type(fps) is not int or not 1 <= fps <= 120
        or type(frames) is not int or frames < 1 or frames > 600 * fps
        or type(width) is not int or width < 2 or width % 2
        or type(height) is not int or height < 2 or height % 2
        or not isinstance(expected_sha256, str)
        or re.fullmatch(r'[a-f0-9]{64}', expected_sha256) is None
    ):
        raise VerificationFailure('invalid_expectations')
    if not path.is_file():
        raise VerificationFailure('media_missing')
    try:
        with path.open('rb') as handle:
            digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    except OSError as exc:
        raise VerificationFailure('media_unreadable') from exc
    if not hmac.compare_digest(digest, expected_sha256):
        raise VerificationFailure('hash_mismatch')

    probe = _run([
        ffprobe, '-v', 'error', '-select_streams', 'v:0',
        '-show_entries',
        'stream=codec_type,codec_name,width,height,avg_frame_rate,nb_frames:format=duration',
        '-of', 'json', str(path),
    ], 120)
    if probe.returncode != 0:
        raise VerificationFailure('probe_failed')
    try:
        info = json.loads(probe.stdout)
        stream = next(s for s in info['streams'] if s.get('codec_type') == 'video')
        actual_fps = Fraction(stream['avg_frame_rate'])
        actual_frames = int(stream['nb_frames'])
        actual_width = int(stream['width'])
        actual_height = int(stream['height'])
        duration = float(info['format']['duration'])
        codec = stream['codec_name']
    except (KeyError, TypeError, ValueError, IndexError, StopIteration, ZeroDivisionError) as exc:
        raise VerificationFailure('probe_invalid') from exc
    if (
        codec != 'h264' or actual_fps != fps or actual_frames != frames
        or (actual_width, actual_height) != (width, height)
        or not math.isfinite(duration) or duration <= 0
        or duration > 600.001
        or abs(duration - frames / fps) > 0.5 / fps + 0.002
    ):
        raise VerificationFailure('metadata_mismatch')

    decoded = _run([
        ffmpeg, '-nostdin', '-v', 'error', '-xerror', '-err_detect', 'explode',
        '-i', str(path), '-map', '0:v:0', '-an', '-f', 'null', '-',
    ], 43200)
    if decoded.returncode != 0:
        raise VerificationFailure('decode_failed')
    return {
        'verified': True, 'codec': 'h264', 'fps': fps,
        'frames': frames, 'width': width, 'height': height,
        'duration_seconds': duration,
        'full_decode_verified': True,
        'actual_model_inference_verified': False,
        'owner_mobile_playback_verified': False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Offline local MP4 master integrity acceptance')
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
        result = verify_master(
            args.mp4, expected_sha256=args.expected_sha256, fps=args.fps,
            frames=args.frames, width=args.width, height=args.height,
            ffprobe=args.ffprobe, ffmpeg=args.ffmpeg,
        )
    except VerificationFailure as exc:
        print(json.dumps({'verified': False, 'reason': exc.reason}))
        return 2
    except Exception:
        # Unexpected exceptions must not reveal local paths, tokens or prompts.
        print(json.dumps({'verified': False, 'reason': 'verification_failed'}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
