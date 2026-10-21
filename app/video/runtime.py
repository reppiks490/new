from __future__ import annotations

import os
import subprocess
from typing import TypedDict

from app.video.models import EngineProfile, VideoRuntimeReport


BALANCED_MIN_MB = 15 * 1024
HIGH_QUALITY_MIN_MB = 31 * 1024


class NvidiaGpuInfo(TypedDict):
    name: str
    total_mb: int
    free_mb: int


def _env_enabled(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {'0', 'false', 'no', 'off'}


def detect_nvidia_gpu() -> NvidiaGpuInfo | None:
    try:
        completed = subprocess.run(
            [
                'nvidia-smi',
                '--query-gpu=name,memory.total,memory.free',
                '--format=csv,noheader,nounits',
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    line = next((row.strip() for row in completed.stdout.splitlines() if row.strip()), '')
    if not line:
        return None
    try:
        name, total, free = [part.strip() for part in line.rsplit(',', 2)]
        return {
            'name': name,
            'total_mb': int(float(total)),
            'free_mb': int(float(free)),
        }
    except (TypeError, ValueError):
        return None


def ffmpeg_available() -> bool:
    try:
        completed = subprocess.run(
            ['ffmpeg', '-version'],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def recommended_profile(report: VideoRuntimeReport) -> EngineProfile | None:
    if not report.cuda_available or not report.ffmpeg_available or report.vram_total_mb is None:
        return None
    if report.vram_total_mb >= HIGH_QUALITY_MIN_MB:
        return 'high_quality'
    if report.vram_total_mb >= BALANCED_MIN_MB:
        return 'balanced'
    return None


def detect_video_runtime() -> VideoRuntimeReport:
    enabled = _env_enabled('CHARACTER3D_VIDEO_ENABLED', True)
    gpu = detect_nvidia_gpu()
    encoder_available = ffmpeg_available()
    cuda_hardware_available = gpu is not None
    blockers: list[str] = []

    if not enabled:
        blockers.append('Local video generation is disabled by CHARACTER3D_VIDEO_ENABLED.')
    if gpu is None:
        blockers.append('No NVIDIA GPU was detected for local image-to-video generation.')
    elif gpu['total_mb'] < BALANCED_MIN_MB:
        blockers.append(
            f'Detected GPU has less than {BALANCED_MIN_MB} MiB VRAM required by the conservative LTX-2.5 profile.'
        )
    if not encoder_available:
        blockers.append('FFmpeg is required to validate and serve generated MP4 video.')

    report = VideoRuntimeReport(
        enabled=enabled,
        available=not blockers,
        gpu_name=gpu['name'] if gpu else None,
        vram_total_mb=gpu['total_mb'] if gpu else None,
        vram_free_mb=gpu['free_mb'] if gpu else None,
        cuda_available=cuda_hardware_available,
        ffmpeg_available=encoder_available,
        blockers=blockers,
        notes=[
            'The FastAPI environment does not need PyTorch; production inference runs in a separate pinned LTX Python environment.',
            'The 15 GiB floor is intentionally conservative; lower-VRAM optimized paths are not claimed until verified on the target PC.',
            'Video generation has no paid-provider fallback; unavailable local hardware remains unavailable.',
        ],
    )
    report.recommended_profile = recommended_profile(report)
    return report
