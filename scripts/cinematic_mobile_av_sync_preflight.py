"""Optional read-only A/V presentation-timestamp alignment gate for private MP4s.

Runs *after* the trusted SHA, full decode, mobile profile, faststart and AAC
checks in QA17–21. This is stream-level alignment, not semantic lip-sync,
private HTTP playback, device compatibility or model inference proof.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from scripts.cinematic_mobile_audio_preflight import verify_mobile_audio
from scripts.cinematic_master_acceptance import VerificationFailure, _run


_MAX_ENDPOINT_SKEW_SECONDS = 0.050


def verify_mobile_av_sync(
    path: Path, *, expected_sha256: str, fps: int, frames: int,
    width: int, height: int, require_audio: bool = False,
    ffprobe: str = 'ffprobe', ffmpeg: str = 'ffmpeg',
) -> dict:
    """Fail closed when decoded AAC starts/ends >50ms from decoded video.

    Compare stream presentation intervals, not only durations. Audio that
    starts late and ends on time can satisfy QA21's 125ms duration tolerance.
    All output is privacy-minimized; no media, path, prompt or tool stderr.
    """
    baseline = verify_mobile_audio(
        path, expected_sha256=expected_sha256, fps=fps, frames=frames,
        width=width, height=height, require_audio=require_audio,
        ffprobe=ffprobe, ffmpeg=ffmpeg,
    )
    if not baseline['audio_present']:
        return {
            **baseline, 'av_stream_timing_verified': False,
            'av_stream_timing_not_applicable': True,
            'owner_mobile_playback_verified': False,
        }
    probe = _run([
        ffprobe, '-v', 'error', '-show_entries',
        'stream=codec_type,start_time,duration', '-of', 'json', str(path),
    ], 120)
    if probe.returncode != 0:
        raise VerificationFailure('mobile_av_timing_probe_failed')
    try:
        streams = json.loads(probe.stdout)['streams']
        if not isinstance(streams, list) or not all(isinstance(s, dict) for s in streams):
            raise ValueError('invalid stream list')
        video = [s for s in streams if s.get('codec_type') == 'video']
        audio = [s for s in streams if s.get('codec_type') == 'audio']
        if len(video) != 1 or len(audio) != 1 or len(streams) != 2:
            raise ValueError('unexpected streams')
        video_start = float(video[0]['start_time'])
        audio_start = float(audio[0]['start_time'])
        video_duration = float(video[0]['duration'])
        audio_duration = float(audio[0]['duration'])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise VerificationFailure('mobile_av_timing_probe_invalid') from exc
    if not all(math.isfinite(x) for x in (
        video_start, audio_start, video_duration, audio_duration,
    )) or video_duration <= 0 or audio_duration <= 0:
        raise VerificationFailure('mobile_av_timing_probe_invalid')
    start_skew = abs(audio_start - video_start)
    end_skew = abs((audio_start + audio_duration) - (video_start + video_duration))
    if start_skew > _MAX_ENDPOINT_SKEW_SECONDS or end_skew > _MAX_ENDPOINT_SKEW_SECONDS:
        raise VerificationFailure('mobile_av_presentation_mismatch')
    return {
        **baseline, 'av_stream_timing_verified': True,
        'av_stream_timing_not_applicable': False,
        'av_start_skew_seconds': round(start_skew, 6),
        'av_end_skew_seconds': round(end_skew, 6),
        'owner_mobile_playback_verified': False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Offline private MP4 A/V stream timing acceptance')
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
        result = verify_mobile_av_sync(
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
