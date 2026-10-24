"""Optional read-only FFprobe audit of cinematic source duration coverage.

Never publishes media, edits a project, or reads prompts. Metadata evidence
cannot establish decoded frame continuity, artistic quality, or real inference.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from fractions import Fraction
import json
from pathlib import Path
import subprocess


class SourceCoverageProbeError(RuntimeError):
    """Neutral diagnostics: never include owner filenames or FFmpeg stderr."""


def _positive_decimal(value: object) -> Decimal | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() and number > 0 else None


def assess_source_probe(probe: object, *, required_frames: int, delivery_fps: int) -> dict:
    """Evaluate *video-stream* duration, not longer audio/container duration.

    Half a delivery frame is the conservative uncertainty band for rounded
    stream metadata. A nominal result is NOT proof of complete decoded frames.
    """
    if type(required_frames) is not int or not 1 <= required_frames <= 72000:
        raise ValueError('required_frames must be 1..72000')
    if type(delivery_fps) is not int or not 1 <= delivery_fps <= 120:
        raise ValueError('delivery_fps must be 1..120')
    if not isinstance(probe, dict) or not isinstance(probe.get('streams'), list):
        raise SourceCoverageProbeError('Source video metadata is unavailable')
    videos = [s for s in probe['streams'] if isinstance(s, dict) and s.get('codec_type') == 'video']
    if len(videos) != 1:
        raise SourceCoverageProbeError('Expected exactly one video stream')
    stream = videos[0]
    duration = _positive_decimal(stream.get('duration'))
    required = Decimal(required_frames) / Decimal(delivery_fps)
    result = {
        'coverage': 'unknown',
        'required_frames': required_frames,
        'delivery_fps': delivery_fps,
        'required_seconds': float(required),
        'observed_video_seconds': float(duration) if duration is not None else None,
        'shortfall_seconds': None,
        'source_fps': None,
        'source_reported_frames': None,
        'evidence': 'ffprobe_stream_metadata_only',
    }
    fps_text = stream.get('avg_frame_rate')
    if isinstance(fps_text, str):
        try:
            fps = Fraction(fps_text)
            if fps > 0:
                result['source_fps'] = str(fps)
        except (ValueError, ZeroDivisionError, OverflowError):
            pass
    reported = stream.get('nb_frames')
    if isinstance(reported, str) and reported.isdecimal():
        result['source_reported_frames'] = int(reported)
    if duration is None:
        return result
    gap = required - duration
    result['shortfall_seconds'] = float(max(Decimal(0), gap))
    result['coverage'] = 'underlength' if gap > Decimal(1) / (2 * delivery_fps) else 'nominal'
    return result


def audit_source_file(
    source_path: str | Path, *, required_frames: int, delivery_fps: int,
    ffprobe_path: str = 'ffprobe', timeout_seconds: int = 30,
) -> dict:
    """Inspect one local source. Never return paths, stderr, or owner content."""
    if not isinstance(ffprobe_path, str) or ffprobe_path not in ('ffprobe', 'ffprobe.exe'):
        raise ValueError('Only local FFprobe executable names are allowed')
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 120:
        raise ValueError('Invalid probe timeout')
    # Validate before launching the process.
    assess_source_probe({'streams': [{'codec_type': 'video'}]},
                        required_frames=required_frames, delivery_fps=delivery_fps)
    try:
        completed = subprocess.run(
            [ffprobe_path, '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=codec_type,duration,avg_frame_rate,nb_frames',
             '-of', 'json', str(source_path)],
            capture_output=True, text=True, timeout=timeout_seconds, check=False,
        )
        if completed.returncode != 0:
            raise SourceCoverageProbeError('Source video could not be probed')
        data = json.loads(completed.stdout)
    except (OSError, subprocess.TimeoutExpired, UnicodeError, json.JSONDecodeError):
        raise SourceCoverageProbeError('Source video could not be probed') from None
    return assess_source_probe(data, required_frames=required_frames, delivery_fps=delivery_fps)
