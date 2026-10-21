from __future__ import annotations

import importlib.util
import os
import subprocess

from app.video.models import VideoRuntimeReport


LOW_VRAM_MIN_MB = 8 * 1024
BALANCED_VRAM_MIN_MB = 16 * 1024
HIGH_QUALITY_VRAM_MIN_MB = 24 * 1024


def _torch_state() -> tuple[bool, bool, str | None]:
    if importlib.util.find_spec('torch') is None:
        return False, False, None
    try:
        import torch
        cuda_available = bool(torch.cuda.is_available())
        cuda_version = getattr(torch.version, 'cuda', None)
        return True, cuda_available, f'CUDA {cuda_version}' if cuda_version else None
    except Exception:
        return True, False, None


def detect_nvidia_gpu() -> dict[str, int | str] | None:
    try:
        cp = subprocess.run(
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
    if cp.returncode != 0 or not cp.stdout.strip():
        return None
    first = cp.stdout.strip().splitlines()[0]
    parts = [part.strip() for part in first.split(',')]
    if len(parts) != 3:
        return None
    try:
        return {'name': parts[0], 'total_mb': int(float(parts[1])), 'free_mb': int(float(parts[2]))}
    except ValueError:
        return None


def ffmpeg_available() -> bool:
    try:
        cp = subprocess.run(
            ['ffmpeg', '-version'],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        return cp.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def recommended_profile(report: VideoRuntimeReport) -> str | None:
    total = report.vram_total_mb or 0
    if total >= HIGH_QUALITY_VRAM_MIN_MB:
        return 'high_quality'
    if total >= BALANCED_VRAM_MIN_MB:
        return 'balanced'
    if total >= LOW_VRAM_MIN_MB:
        return 'low_vram'
    return None


def detect_video_runtime() -> VideoRuntimeReport:
    enabled = os.getenv('CHARACTER3D_VIDEO_ENABLED', '1').strip().lower() not in {'0', 'false', 'no', 'off'}
    torch_available, cuda_available, torch_cuda_detail = _torch_state()
    gpu = detect_nvidia_gpu()
    has_ffmpeg = ffmpeg_available()

    blockers: list[str] = []
    notes: list[str] = ['Video generation is local-only; no paid inference fallback is configured.']
    if torch_cuda_detail:
        notes.append(torch_cuda_detail)
    if not enabled:
        blockers.append('Local video generation is disabled by CHARACTER3D_VIDEO_ENABLED.')
    if not torch_available:
        blockers.append('PyTorch is not installed; local CUDA inference is unavailable.')
    elif not cuda_available:
        blockers.append('CUDA is unavailable to PyTorch; a compatible NVIDIA GPU/runtime is required for the configured local engines.')
    if gpu is None:
        blockers.append('NVIDIA GPU details could not be detected with nvidia-smi.')
    if not has_ffmpeg:
        blockers.append('FFmpeg is unavailable; MP4 encoding cannot run.')

    report = VideoRuntimeReport(
        enabled=enabled,
        available=False,
        gpu_name=str(gpu['name']) if gpu else None,
        vram_total_mb=int(gpu['total_mb']) if gpu else None,
        vram_free_mb=int(gpu['free_mb']) if gpu else None,
        cuda_available=cuda_available,
        torch_available=torch_available,
        ffmpeg_available=has_ffmpeg,
        blockers=blockers,
        notes=notes,
    )
    profile = recommended_profile(report)
    if profile is None and gpu is not None:
        blockers.append(f"Detected {report.vram_total_mb} MiB VRAM, below the current local-video profile floor of {LOW_VRAM_MIN_MB} MiB.")
    report.recommended_profile = profile
    report.available = bool(enabled and torch_available and cuda_available and gpu and has_ffmpeg and profile)
    return report
