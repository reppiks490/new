"""Offline, privacy-minimal owner-PC readiness checks for local cinematic FFmpeg.

No workspace files are opened or changed. An optional synthetic smoke test writes
only to a private temporary directory and never consumes owner media.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile


def _invoke(command: list[str], *, timeout: int = 15):
    return subprocess.run(command, capture_output=True, text=True,
                          timeout=timeout, check=False)


def _ok(command: list[str], *, timeout: int = 15) -> bool:
    try:
        return _invoke(command, timeout=timeout).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _encoder_present(ffmpeg: str) -> bool:
    try:
        result = _invoke([ffmpeg, '-hide_banner', '-encoders'])
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and bool(re.search(
        r'^\s*V\S*\s+libx264(?:\s|$)', result.stdout, re.MULTILINE,
    ))


def _synthetic_smoke(ffmpeg: str, ffprobe: str) -> bool:
    """Encode, probe, and fully decode exactly 24 synthetic 160x90 frames."""
    try:
        with tempfile.TemporaryDirectory(prefix='cinematic-qa35-') as folder:
            video = Path(folder) / 'synthetic.mp4'
            encoded = _invoke([
                ffmpeg, '-nostdin', '-y', '-hide_banner', '-loglevel', 'error',
                '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=24:duration=1',
                '-frames:v', '24', '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart', str(video),
            ], timeout=60)
            if encoded.returncode or not video.is_file() or video.stat().st_size < 12:
                return False
            probed = _invoke([
                ffprobe, '-v', 'error', '-select_streams', 'v:0',
                '-show_entries', 'stream=codec_name,width,height,avg_frame_rate,nb_frames',
                '-of', 'json', str(video),
            ], timeout=20)
            if probed.returncode:
                return False
            streams = json.loads(probed.stdout)['streams']
            if len(streams) != 1:
                return False
            stream = streams[0]
            if not (stream.get('codec_name') == 'h264'
                    and int(stream['width']) == 160
                    and int(stream['height']) == 90
                    and int(stream['nb_frames']) == 24
                    and stream['avg_frame_rate'] == '24/1'):
                return False
            return _ok([ffmpeg, '-nostdin', '-v', 'error', '-i', str(video),
                        '-f', 'null', '-'], timeout=30)
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError,
            IndexError, json.JSONDecodeError):
        return False


def inspect_local_readiness(workspace: Path, *, min_free_bytes: int = 20 * 1024**3,
                            synthetic_smoke: bool = False) -> dict:
    """Return path-free diagnostics; no media, credentials, or prompts are read."""
    if type(min_free_bytes) is not int or min_free_bytes < 0:
        raise ValueError('min_free_bytes must be a nonnegative integer')
    checks: dict[str, dict] = {}

    def mark(name: str, passed: bool, reason: str) -> None:
        checks[name] = {'passed': bool(passed), 'code': 'ok' if passed else reason}

    ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    ffmpeg_ok = bool(ffmpeg and _ok([ffmpeg, '-version']))
    ffprobe_ok = bool(ffprobe and _ok([ffprobe, '-version']))
    mark('ffmpeg_available', ffmpeg_ok, 'ffmpeg_missing_or_unusable')
    mark('ffprobe_available', ffprobe_ok, 'ffprobe_missing_or_unusable')
    encoder_ok = bool(ffmpeg_ok and _encoder_present(ffmpeg))
    mark('h264_encoder_available', encoder_ok, 'libx264_missing_or_unusable')

    # Do not follow a symlink at the final workspace component.
    exists = workspace.is_dir() and not workspace.is_symlink()
    mark('workspace_directory', exists, 'workspace_missing_or_symlink')
    if exists:
        if os.name == 'posix':
            try:
                private = stat.S_IMODE(workspace.stat().st_mode) & 0o077 == 0
            except OSError:
                private = False
            mark('workspace_private_posix', private, 'workspace_permissions_not_private')
        try:
            free = shutil.disk_usage(workspace).free
            mark('disk_headroom_policy', free >= min_free_bytes,
                 'below_configured_free_space_threshold')
        except OSError:
            mark('disk_headroom_policy', False, 'disk_space_unavailable')
    else:
        mark('disk_headroom_policy', False, 'workspace_unavailable')

    if synthetic_smoke:
        smoke_ok = bool(ffmpeg_ok and ffprobe_ok and encoder_ok
                        and _synthetic_smoke(ffmpeg, ffprobe))
        mark('synthetic_encode_probe_decode', smoke_ok, 'synthetic_media_smoke_failed')
    return {
        'schema_version': 1,
        'local_preflight_passed': all(item['passed'] for item in checks.values()),
        'checks': checks,
        'verification_scope': 'local tools and workspace; no model inference or mobile playback',
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path,
                        default=Path(os.environ.get('CHARACTER3D_STUDIO_WORKSPACE',
                                                 './workspace/studio')))
    parser.add_argument('--minimum-free-gib', type=float, default=20.0,
                        help='advisory policy threshold, NOT an estimated film size')
    parser.add_argument('--synthetic-smoke', action='store_true',
                        help='opt in to temporary synthetic FFmpeg encode/probe/decode')
    args = parser.parse_args(argv)
    if not math.isfinite(args.minimum_free_gib) or not 0 <= args.minimum_free_gib <= 4096:
        parser.error('minimum-free-gib must be finite and between 0 and 4096')
    report = inspect_local_readiness(
        args.workspace, min_free_bytes=int(args.minimum_free_gib * 1024**3),
        synthetic_smoke=args.synthetic_smoke,
    )
    print(json.dumps(report, sort_keys=True))
    return 0 if report['local_preflight_passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
