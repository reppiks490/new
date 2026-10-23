"""Optional, read-only AAC-LC/audio-duration gate for private cinematic MP4 masters.

Stacks on QA17/18/19 integrity, H.264 format, and progressive-start gates.
It does not remux, upload, or certify native iPhone playback. Silent films
are valid unless the caller explicitly requires an audio track.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from scripts.cinematic_mobile_progressive_preflight import (
    VerificationFailure,
    verify_mobile_progressive,
)
from scripts.cinematic_master_acceptance import _run


_ALLOWED_SAMPLE_RATES = frozenset({44100, 48000})
_MAX_AUDIO_SKEW_SECONDS = 0.125


def verify_mobile_audio(
    path: Path, *, expected_sha256: str, fps: int, frames: int,
    width: int, height: int, require_audio: bool = False,
    ffprobe: str = 'ffprobe', ffmpeg: str = 'ffmpeg',
) -> dict:
    """Validate AAC-LC mono/stereo and A/V duration after prior MP4 gates.

    Audio is decoded independently because the QA17 full-decode gate maps
    video only. The returned facts never include filenames, subprocess output,
    owner prompts, media bytes, or credentials.
    """
    if type(require_audio) is not bool:
        raise VerificationFailure('invalid_expectations')
    baseline = verify_mobile_progressive(
        path, expected_sha256=expected_sha256, fps=fps, frames=frames,
        width=width, height=height, ffprobe=ffprobe, ffmpeg=ffmpeg,
    )
    probe = _run([
        ffprobe, '-v', 'error', '-show_entries',
        'stream=index,codec_type,codec_name,profile,sample_rate,channels,duration',
        '-of', 'json', str(path),
    ], 120)
    if probe.returncode != 0:
        raise VerificationFailure('mobile_audio_probe_failed')
    try:
        streams = json.loads(probe.stdout)['streams']
        if not isinstance(streams, list) or not all(isinstance(s, dict) for s in streams):
            raise ValueError('invalid streams')
        video = [s for s in streams if s.get('codec_type') == 'video']
        audio = [s for s in streams if s.get('codec_type') == 'audio']
        if len(video) != 1 or len(video) + len(audio) != len(streams) or len(audio) > 1:
            raise VerificationFailure('mobile_audio_stream_layout_unsupported')
    except (KeyError, ValueError, TypeError) as exc:
        raise VerificationFailure('mobile_audio_probe_invalid') from exc
    if not audio:
        if require_audio:
            raise VerificationFailure('mobile_audio_missing')
        return {
            **baseline, 'audio_present': False,
            'audio_absence_verified': True, 'mobile_aac_lc_verified': False,
            'audio_full_decode_verified': False,
            'owner_mobile_playback_verified': False,
        }
    stream = audio[0]
    # Non-AAC codecs need not expose an AAC-style profile at all.
    if stream.get('codec_name') != 'aac':
        raise VerificationFailure('mobile_audio_codec_unsupported')
    try:
        codec = stream['codec_name']
        profile = stream['profile']
        rate = int(stream['sample_rate'])
        channels = int(stream['channels'])
        duration = float(stream['duration'])
    except (KeyError, ValueError, TypeError, OverflowError) as exc:
        raise VerificationFailure('mobile_audio_probe_invalid') from exc
    if (
        codec != 'aac' or profile != 'LC'
        or rate not in _ALLOWED_SAMPLE_RATES or channels not in (1, 2)
    ):
        raise VerificationFailure('mobile_audio_codec_unsupported')
    if (
        not math.isfinite(duration) or duration <= 0
        or abs(duration - baseline['duration_seconds']) > _MAX_AUDIO_SKEW_SECONDS
    ):
        raise VerificationFailure('mobile_audio_duration_mismatch')
    decoded = _run([
        ffmpeg, '-nostdin', '-v', 'error', '-xerror', '-err_detect', 'explode',
        '-i', str(path), '-map', '0:a:0', '-vn', '-f', 'null', '-',
    ], 7200)
    if decoded.returncode != 0:
        raise VerificationFailure('mobile_audio_decode_failed')
    return {
        **baseline, 'audio_present': True,
        'audio_absence_verified': False, 'mobile_aac_lc_verified': True,
        'audio_full_decode_verified': True,
        'audio_duration_seconds': duration,
        'owner_mobile_playback_verified': False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Read-only mobile AAC-LC MP4 audio preflight')
    parser.add_argument('--mp4', type=Path, required=True)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--fps', type=int, required=True)
    parser.add_argument('--frames', type=int, required=True)
    parser.add_argument('--width', type=int, required=True)
    parser.add_argument('--height', type=int, required=True)
    parser.add_argument('--require-audio', action='store_true')
    parser.add_argument('--ffprobe', default='ffprobe')
    parser.add_argument('--ffmpeg', default='ffmpeg')
    args = parser.parse_args(argv)
    try:
        result = verify_mobile_audio(
            args.mp4, expected_sha256=args.expected_sha256,
            fps=args.fps, frames=args.frames, width=args.width, height=args.height,
            require_audio=args.require_audio, ffprobe=args.ffprobe, ffmpeg=args.ffmpeg,
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
