"""Optional offline, read-only display-geometry gate for verified cinematic MP4s.

Checks for non-square pixels and container display transformations after the
trusted-SHA/full-decode/mobile H.264/faststart/audio/timestamp acceptance chain.
A positive result is not proof of physical phone playback or AI inference.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.cinematic_mobile_av_sync_preflight import verify_mobile_av_sync
from scripts.cinematic_master_acceptance import VerificationFailure, _run


def verify_mobile_display_geometry(
    path: Path, *, expected_sha256: str, fps: int, frames: int,
    width: int, height: int, require_audio: bool = False,
    ffprobe: str = 'ffprobe', ffmpeg: str = 'ffmpeg',
) -> dict:
    """Require square pixels and no implicit video display rotation/mirroring.

    This is a *conservative normalized-master policy*, not a claim that every
    rotated/anamorphic MP4 is unplayable on mobile. All diagnostics omit paths,
    source tags, FFmpeg stderr, prompts, credentials and media bytes.
    """
    baseline = verify_mobile_av_sync(
        path, expected_sha256=expected_sha256, fps=fps, frames=frames,
        width=width, height=height, require_audio=require_audio,
        ffprobe=ffprobe, ffmpeg=ffmpeg,
    )
    probe = _run([
        ffprobe, '-v', 'error', '-show_entries',
        'stream=codec_type,sample_aspect_ratio:stream_tags=rotate:'
        'stream_side_data=side_data_type,rotation',
        '-of', 'json', str(path),
    ], 120)
    if probe.returncode != 0:
        raise VerificationFailure('mobile_display_probe_failed')
    try:
        streams = json.loads(probe.stdout)['streams']
        if not isinstance(streams, list):
            raise ValueError('invalid streams')
        videos = [s for s in streams if isinstance(s, dict) and s.get('codec_type') == 'video']
        if len(videos) != 1 or len(videos) + sum(
            isinstance(s, dict) and s.get('codec_type') == 'audio' for s in streams
        ) != len(streams):
            raise ValueError('unexpected streams')
        video = videos[0]
        sar = video['sample_aspect_ratio']
        tags = video.get('tags', {})
        side_data = video.get('side_data_list', [])
        if not isinstance(sar, str) or not isinstance(tags, dict) or not isinstance(side_data, list):
            raise ValueError('invalid geometry')
        if not all(isinstance(s, dict) and isinstance(s.get('side_data_type'), str)
                   for s in side_data):
            raise ValueError('invalid side data')
    except (ValueError, KeyError, TypeError) as exc:
        raise VerificationFailure('mobile_display_probe_invalid') from exc
    # Refuse ambiguous N/A SAR and even zero-degree matrices: a matrix may
    # mirror or scale without rotating, and normalized masters need neither.
    if (sar != '1:1' or 'rotate' in tags or any(
        s['side_data_type'] == 'Display Matrix' for s in side_data
    )):
        raise VerificationFailure('mobile_display_geometry_unsupported')
    return {
        **baseline,
        'mobile_square_pixels_verified': True,
        'mobile_no_display_transform_verified': True,
        'owner_mobile_playback_verified': False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Offline private MP4 display geometry acceptance')
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
        result = verify_mobile_display_geometry(
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
