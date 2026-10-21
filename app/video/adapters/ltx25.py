from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
from typing import Mapping

from PIL import Image

from app.video.models import EngineCapabilities, VideoGenerationRequest
from app.video.runtime import detect_nvidia_gpu


LTX2_RELEASE = '1.5.0'
LTX2_SOURCE_REVISION = 'e98f6d927d83c92ef2be6aec76c8440b19306e39'
LTX25_MIN_VRAM_MB = 15 * 1024
LTX25_HIGH_QUALITY_VRAM_MB = 31 * 1024

LTX25_REQUIRED_FILES: dict[str, str] = {
    'transformer': 'diffusion_models/ltx-2.5-22b-distilled-transformer-bf16.safetensors',
    'text_encoder': 'text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors',
    'video_vae': 'vae/ltx-2.5-video-vae-conv-bf16.safetensors',
    'audio_vae': 'vae/ltx-2.5-audio-vae-bf16.safetensors',
    'spatial_upsampler': 'latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors',
}
LTX25_HIGH_QUALITY_FILES: dict[str, str] = {
    'video_vae': 'vae/ltx-2.5-video-vae-bf16.safetensors',
}

_RESOLUTIONS: dict[str, tuple[int, int, int]] = {
    # landscape width, landscape height, square edge
    '480p': (832, 480, 640),
    '720p': (1280, 704, 960),
    '1080p': (1920, 1088, 1536),
}
_SECRET_ENV_MARKERS = ('KEY', 'TOKEN', 'SECRET', 'PASSWORD')
_ALLOWED_OFFLOAD = {'none', 'cpu', 'disk'}
_ALLOWED_QUANTIZATION = {'', 'fp8-cast', 'fp8-scaled-mm'}


@dataclass(frozen=True)
class LtxPythonProbe:
    available: bool
    version: str | None
    cuda_available: bool
    detail: str


@dataclass(frozen=True)
class Ltx25Paths:
    model_dir: Path
    transformer: Path
    text_encoder: Path
    video_vae: Path
    audio_vae: Path
    spatial_upsampler: Path
    high_quality_video_vae: Path

    @classmethod
    def from_model_dir(cls, model_dir: str | Path) -> 'Ltx25Paths':
        root = Path(model_dir).expanduser()
        return cls(
            model_dir=root,
            transformer=root / LTX25_REQUIRED_FILES['transformer'],
            text_encoder=root / LTX25_REQUIRED_FILES['text_encoder'],
            video_vae=root / LTX25_REQUIRED_FILES['video_vae'],
            audio_vae=root / LTX25_REQUIRED_FILES['audio_vae'],
            spatial_upsampler=root / LTX25_REQUIRED_FILES['spatial_upsampler'],
            high_quality_video_vae=root / LTX25_HIGH_QUALITY_FILES['video_vae'],
        )

    def missing(self) -> list[str]:
        required = [
            self.transformer,
            self.text_encoder,
            self.video_vae,
            self.audio_vae,
            self.spatial_upsampler,
        ]
        return [path.name for path in required if not path.is_file()]

    def high_quality_missing(self) -> list[str]:
        return [] if self.high_quality_video_vae.is_file() else [self.high_quality_video_vae.name]


def _model_dir() -> Path:
    configured = os.getenv('CHARACTER3D_LTX_MODEL_DIR')
    if configured:
        return Path(configured).expanduser()
    return Path(os.getenv('CHARACTER3D_VIDEO_MODEL_DIR', './weights/video')).expanduser() / 'ltx-2.5'


def _python_executable() -> str:
    return os.getenv('CHARACTER3D_LTX_PYTHON', 'python')


def _timeout_seconds() -> int:
    raw = os.getenv('CHARACTER3D_LTX_TIMEOUT_SECONDS', '3600')
    try:
        return max(300, min(24 * 3600, int(raw)))
    except ValueError:
        return 3600


def _offload_mode() -> str:
    value = os.getenv('CHARACTER3D_LTX_OFFLOAD', 'disk').strip().lower()
    return value if value in _ALLOWED_OFFLOAD else 'disk'


def _quantization() -> str:
    value = os.getenv('CHARACTER3D_LTX_QUANTIZATION', '').strip().lower()
    return value if value in _ALLOWED_QUANTIZATION else ''


def snap_ltx_frames(duration_seconds: float, fps: int) -> int:
    target = max(1, int(round(float(duration_seconds) * int(fps))))
    k = max(0, int(round((target - 1) / 8)))
    return 8 * k + 1


def ltx_dimensions(resolution: str, source_path: str | Path) -> tuple[int, int]:
    if resolution not in _RESOLUTIONS:
        raise ValueError(f'Unsupported LTX resolution preset: {resolution}')
    with Image.open(source_path) as image:
        source_width, source_height = image.size
    landscape_width, landscape_height, square_edge = _RESOLUTIONS[resolution]
    ratio = source_width / max(1, source_height)
    if 0.9 <= ratio <= 1.1:
        return square_edge, square_edge
    if source_width >= source_height:
        return landscape_width, landscape_height
    return landscape_height, landscape_width


def probe_ltx_python(executable: str) -> LtxPythonProbe:
    command = [
        executable,
        '-c',
        (
            "import importlib.metadata as m; import torch; import ltx_pipelines; "
            "print(m.version('ltx-pipelines')); print(int(torch.cuda.is_available()))"
        ),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return LtxPythonProbe(False, None, False, f'ltx-pipelines unavailable: {exc.__class__.__name__}')
    if completed.returncode != 0:
        return LtxPythonProbe(False, None, False, 'ltx-pipelines unavailable in configured Python environment')
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    version = lines[0] if lines else None
    cuda_available = len(lines) > 1 and lines[1] == '1'
    if version != LTX2_RELEASE:
        return LtxPythonProbe(False, version, cuda_available, f'ltx-pipelines {LTX2_RELEASE} is required')
    if not cuda_available:
        return LtxPythonProbe(False, version, False, 'Configured LTX Python environment cannot access CUDA')
    return LtxPythonProbe(True, version, True, 'LTX-2.5 local runtime ready')


def _sanitized_child_env(source: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(source or os.environ)
    for name in list(env):
        upper = name.upper()
        if any(marker in upper for marker in _SECRET_ENV_MARKERS):
            env.pop(name, None)
    env['HF_HUB_OFFLINE'] = '1'
    env['TRANSFORMERS_OFFLINE'] = '1'
    return env


class Ltx25LocalEngine:
    name = 'ltx25_local'

    def __init__(self, *, python_executable: str | None = None, model_dir: str | Path | None = None):
        self.python_executable = python_executable or _python_executable()
        self.paths = Ltx25Paths.from_model_dir(model_dir or _model_dir())

    def capabilities(self) -> EngineCapabilities:
        probe = probe_ltx_python(self.python_executable)
        gpu = detect_nvidia_gpu()
        missing = self.paths.missing()
        problems: list[str] = []
        if not probe.available:
            problems.append(probe.detail)
        if gpu is None:
            problems.append('No NVIDIA GPU detected')
        elif gpu['total_mb'] < LTX25_MIN_VRAM_MB:
            problems.append(f'At least {LTX25_MIN_VRAM_MB} MiB VRAM is required by this conservative LTX profile')
        if missing:
            problems.append('Missing model components: ' + ', '.join(missing))

        profiles: list[str] = []
        resolutions: list[str] = []
        if not problems:
            profiles.append('balanced')
            resolutions.extend(['480p', '720p'])
            if gpu is not None and gpu['total_mb'] >= LTX25_HIGH_QUALITY_VRAM_MB and not self.paths.high_quality_missing():
                profiles.append('high_quality')
                resolutions.append('1080p')

        detail = '; '.join(problems) if problems else (
            f'LTX-2.5 local runtime ready (ltx-pipelines {probe.version}, pinned source {LTX2_SOURCE_REVISION[:12]}).'
        )
        return EngineCapabilities(
            name=self.name,
            available=not problems,
            profiles=profiles,  # type: ignore[arg-type]
            supported_resolutions=resolutions,  # type: ignore[arg-type]
            min_duration_seconds=1,
            max_duration_seconds=30,
            supported_fps=[24] if not problems else [],
            supports_motion_strength=False,
            camera_motion_presets=[],
            detail=detail,
        )

    def _video_vae_for(self, request: VideoGenerationRequest) -> Path:
        if request.engine_profile == 'high_quality':
            return self.paths.high_quality_video_vae
        return self.paths.video_vae

    def build_command(
        self,
        request: VideoGenerationRequest,
        source_path: str | Path,
        output_path: str | Path,
    ) -> list[str]:
        source = Path(source_path)
        output = Path(output_path)
        width, height = ltx_dimensions(request.resolution, source)
        frames = snap_ltx_frames(request.duration_seconds, request.fps)
        command = [
            self.python_executable,
            '-m',
            'ltx_pipelines.distilled',
            '--transformer-path', str(self.paths.transformer),
            '--text-encoder-path', str(self.paths.text_encoder),
            '--video-vae-path', str(self._video_vae_for(request)),
            '--audio-vae-path', str(self.paths.audio_vae),
            '--spatial-upsampler-path', str(self.paths.spatial_upsampler),
            '--prompt', request.prompt,
            '--seed', str(request.seed),
            '--width', str(width),
            '--height', str(height),
            '--num-frames', str(frames),
            '--frame-rate', str(request.fps),
            '--image', str(source), '0', '1.0',
            '--offload', _offload_mode(),
            '--output-path', str(output),
        ]
        quantization = _quantization()
        if quantization:
            output_index = command.index('--output-path')
            command[output_index:output_index] = ['--quantization', quantization]
        return command

    def generate(
        self,
        *,
        request: VideoGenerationRequest,
        source_path: Path,
        output_path: Path,
        progress,
    ) -> Path:
        from app.video.engine import validate_request_for_engine

        capabilities = self.capabilities()
        validate_request_for_engine(request, capabilities)
        if not capabilities.available:
            raise RuntimeError(capabilities.detail)
        if not source_path.is_file():
            raise FileNotFoundError('Source image does not exist')
        output_path.parent.mkdir(parents=True, exist_ok=True)
        progress('generating', 15)
        try:
            completed = subprocess.run(
                self.build_command(request, source_path, output_path),
                capture_output=True,
                text=True,
                check=False,
                timeout=_timeout_seconds(),
                shell=False,
                env=_sanitized_child_env(),
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('LTX-2.5 local generation exceeded the configured timeout') from exc
        except OSError as exc:
            raise RuntimeError('LTX-2.5 local runtime could not be started') from exc
        if completed.returncode != 0:
            raise RuntimeError(f'LTX-2.5 local generation failed with exit code {completed.returncode}')
        if not output_path.is_file():
            raise RuntimeError('LTX-2.5 local generation completed without an MP4 output')
        progress('encoding', 95)
        return output_path
