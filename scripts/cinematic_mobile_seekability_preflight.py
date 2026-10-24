"""QA25: optional offline, read-only CFR and seek-keyframe acceptance for private MP4s.

The preceding QA17-24 chain verifies integrity, full decode, mobile codec,
faststart, audio/timestamp alignment and display geometry. Those checks do
not bound the time a mobile player must decode after seeking into a long film.
This conservative normalized-master gate inspects *all* video packet PTS and
keyframe flags, never uploads or rewrites media, and is not phone playback proof.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from scripts.cinematic_mobile_display_geometry_preflight import verify_mobile_display_geometry
from scripts.cinematic_master_acceptance import VerificationFailure, _run


_MAX_SEEK_GAP_SECONDS = 2.0


def verify_mobile_seekability(
    path: Path, *, expected_sha256: str, fps: int, frames: int,
    width: int, height: int, require_audio: bool = False,
    ffprobe: str = 'ffprobe', ffmpeg: str = 'ffmpeg',
) -> dict:
    """Require frame-regular presentation and a keyframe within every 2s span.

    A positive result is a *container-level seekability policy*, not a
    measured seek latency or a guarantee of iOS/browser hardware behavior.
    Errors and success results omit media paths, tags, stderr and credentials.
    """
    baseline = verify_mobile_display_geometry(
        path, expected_sha256=expected_sha256, fps=fps, frames=frames,
        width=width, height=height, require_audio=require_audio,
        ffprobe=ffprobe, ffmpeg=ffmpeg,
    )
    probe = _run([
        ffprobe, '-v', 'error', '-select_streams', 'v:0',
        '-show_packets', '-show_entries', 'packet=pts_time,flags',
        '-of', 'json', str(path),
    ], 120)
    if probe.returncode != 0:
        raise VerificationFailure('mobile_seek_packet_probe_failed')
    try:
        packets = json.loads(probe.stdout)['packets']
        if not isinstance(packets, list) or len(packets) != frames:
            raise ValueError('unexpected video packet count')
        parsed = []
        for packet in packets:
            if not isinstance(packet, dict) or not isinstance(packet.get('flags'), str):
                raise ValueError('invalid packet')
            pts = float(packet['pts_time'])
            if not math.isfinite(pts):
                raise ValueError('nonfinite packet timestamp')
            parsed.append((pts, packet['flags'].startswith('K')))
        parsed.sort(key=lambda item: item[0])
        times = [item[0] for item in parsed]
        keys = [item[0] for item in parsed if item[1]]
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise VerificationFailure('mobile_seek_packet_probe_invalid') from exc

    frame_period = 1.0 / fps
    duration = frames / fps
    # MP4 B-frame packets arrive in decode order, so sort by PTS first.
    # The normalized output policy is CFR, not merely a correct *average* FPS.
    if (not times or abs(times[0]) > frame_period / 2 + 0.002
            or abs(times[-1] - (frames - 1) * frame_period) > frame_period / 2 + 0.002
            or any(abs((b - a) - frame_period) > frame_period / 2 + 0.002
                   for a, b in zip(times, times[1:]))):
        raise VerificationFailure('mobile_video_packet_timing_irregular')
    if not keys:
        raise VerificationFailure('mobile_seek_keyframes_missing')
    gaps = [keys[0]] + [
        right - left for left, right in zip(keys, keys[1:])
    ] + [duration - keys[-1]]
    largest_gap = max(gaps)
    if largest_gap > _MAX_SEEK_GAP_SECONDS + 0.002:
        raise VerificationFailure('mobile_seek_keyframe_gap_exceeded')
    return {
        **baseline,
        'mobile_video_packet_cfr_verified': True,
        'mobile_keyframe_seek_window_verified': True,
        'max_keyframe_gap_seconds': round(largest_gap, 6),
        'keyframe_count': len(keys),
        'owner_mobile_playback_verified': False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Offline MP4 mobile seek/keyframe preflight')
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
        result = verify_mobile_seekability(
            args.mp4, expected_sha256=args.expected_sha256, fps=args.fps,
            frames=args.frames, width=args.width, height=args.height,
            require_audio=args.require_audio, ffprobe=args.ffprobe,
            ffmpeg=args.ffmpeg,
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
