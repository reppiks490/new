"""QA31: read-only MP4 stream inventory gate for private mobile masters.

QA17 verifies the first video stream and its complete decode, but does not
assert that the MP4 has no *other* streams. This optional gate rejects extra
video, subtitle, timed-data, attachment, and unapproved audio streams.

This is offline synthetic-media acceptance, not owner-device playback,
model inference, or proof of the production assembler's stream mapping.
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


def verify_master_stream_inventory(
    path: Path, *, expected_sha256: str, fps: int, frames: int,
    width: int, height: int, allow_aac_audio: bool = False,
    ffprobe: str = 'ffprobe', ffmpeg: str = 'ffmpeg',
) -> dict:
    """Require trusted SHA, first-video full decode, then a closed stream set.

    When allow_aac_audio=True, this only checks the audio stream's presence and
    codec identity. Audio decoding, A/V synchronization and mobile playback
    must be independently verified by the appropriate acceptance gates.
    No source path, private tag, media bytes or subprocess output is returned.
    """
    if type(allow_aac_audio) is not bool:
        raise VerificationFailure('invalid_expectations')
    baseline = verify_master(
        path, expected_sha256=expected_sha256, fps=fps, frames=frames,
        width=width, height=height, ffprobe=ffprobe, ffmpeg=ffmpeg,
    )
    probe = _run([
        ffprobe, '-v', 'error',
        '-show_entries', 'stream=index,codec_type,codec_name:format=format_name',
        '-of', 'json', str(path),
    ], 120)
    if probe.returncode != 0:
        raise VerificationFailure('stream_inventory_probe_failed')
    try:
        info = json.loads(probe.stdout)
        streams = info['streams']
        container = info['format']['format_name']
        if (
            not isinstance(streams, list)
            or not streams
            or not isinstance(container, str)
            or 'mp4' not in container.split(',')
        ):
            raise ValueError('invalid stream inventory')
        indices = []
        for stream in streams:
            if (
                not isinstance(stream, dict)
                or type(stream.get('index')) is not int
                or stream['index'] < 0
                or not isinstance(stream.get('codec_type'), str)
                or not isinstance(stream.get('codec_name'), str)
            ):
                raise ValueError('invalid stream fields')
            indices.append(stream['index'])
        if len(indices) != len(set(indices)):
            raise ValueError('duplicate stream index')
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise VerificationFailure('stream_inventory_invalid') from exc

    video = [stream for stream in streams if stream['codec_type'] == 'video']
    audio = [stream for stream in streams if stream['codec_type'] == 'audio']
    other = [
        stream for stream in streams
        if stream['codec_type'] not in {'video', 'audio'}
    ]
    if len(video) != 1 or video[0]['codec_name'] != 'h264':
        raise VerificationFailure('unexpected_video_stream_count')
    if other:
        raise VerificationFailure('unexpected_auxiliary_stream')
    if audio:
        if not allow_aac_audio or len(audio) != 1:
            raise VerificationFailure('unexpected_audio_stream')
        if audio[0]['codec_name'] != 'aac':
            raise VerificationFailure('unexpected_audio_codec')

    return {
        **baseline,
        'stream_inventory_verified': True,
        'video_stream_count': 1,
        'audio_stream_count': len(audio),
        'auxiliary_stream_count': 0,
        'audio_decode_verified': False,
        'owner_mobile_playback_verified': False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Read-only private MP4 stream-inventory acceptance'
    )
    parser.add_argument('--mp4', type=Path, required=True)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--fps', type=int, required=True)
    parser.add_argument('--frames', type=int, required=True)
    parser.add_argument('--width', type=int, required=True)
    parser.add_argument('--height', type=int, required=True)
    parser.add_argument('--allow-aac-audio', action='store_true')
    parser.add_argument('--ffprobe', default='ffprobe')
    parser.add_argument('--ffmpeg', default='ffmpeg')
    args = parser.parse_args(argv)
    try:
        result = verify_master_stream_inventory(
            args.mp4, expected_sha256=args.expected_sha256,
            fps=args.fps, frames=args.frames, width=args.width,
            height=args.height, allow_aac_audio=args.allow_aac_audio,
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
