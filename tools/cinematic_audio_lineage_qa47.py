"""Opt-in, privacy-minimized source-to-master audio presence check.

This does not verify sound quality, A/V sync, provenance, or whether muting
was intentional. It never returns media paths or embedded metadata.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
from typing import Sequence


class MediaProbeError(RuntimeError):
    """Sanitized probe failure; never include FFmpeg output or file paths."""


def _has_streams(path: Path, *, ffprobe: str, timeout: float) -> tuple[bool, bool]:
    try:
        completed = subprocess.run(
            [ffprobe, '-v', 'error', '-show_entries', 'stream=codec_type',
             '-of', 'json', str(path)],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
        if completed.returncode != 0 or len(completed.stdout) > 1024 * 1024:
            raise MediaProbeError('Local media stream inspection failed')
        data = json.loads(completed.stdout)
        streams = data['streams']
        if not isinstance(streams, list):
            raise ValueError('Invalid stream list')
        types = {item['codec_type'] for item in streams if isinstance(item, dict)
                 and isinstance(item.get('codec_type'), str)}
        if 'video' not in types:
            raise MediaProbeError('Local media has no usable video stream')
        return True, 'audio' in types
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
        raise MediaProbeError('Local media stream inspection failed') from None


def audit_audio_presence(
    sources: Sequence[Path], master: Path, *, ffprobe: str = 'ffprobe',
    timeout: float = 30.0,
) -> dict:
    """Check only stream presence, not content or timestamps.

    Inputs are explicit local paths supplied by the operator. Do not use
    network URLs or accept an untrusted ffprobe executable from an API.
    """
    if not 1 <= len(sources) <= 1000 or timeout <= 0 or timeout > 120:
        raise ValueError('Source count or probe timeout is outside safe bounds')
    if ffprobe not in ('ffprobe', 'ffprobe.exe'):
        raise ValueError('Only local FFprobe binary names are supported')
    source_audio = 0
    for source in sources:
        _, has_audio = _has_streams(Path(source), ffprobe=ffprobe, timeout=timeout)
        source_audio += int(has_audio)
    _, master_audio = _has_streams(Path(master), ffprobe=ffprobe, timeout=timeout)
    if source_audio and not master_audio:
        state = 'source_audio_absent_from_master'
    elif source_audio and master_audio:
        state = 'audio_present_provenance_unverified'
    elif master_audio:
        state = 'master_audio_without_source_audio'
    else:
        state = 'video_only_sources_and_master'
    return {
        'source_count': len(sources),
        'sources_with_audio': source_audio,
        'master_has_audio': master_audio,
        'state': state,
        'audio_content_or_sync_verified': False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Offline path-free cinematic audio lineage report')
    parser.add_argument('--source', type=Path, action='append', required=True)
    parser.add_argument('--master', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = audit_audio_presence(args.source, args.master)
    except (MediaProbeError, ValueError):
        print(json.dumps({'state': 'inspection_failed', 'audio_content_or_sync_verified': False}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
