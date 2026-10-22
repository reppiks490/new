from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
from typing import Mapping

from PIL import Image

from app.image.models import ImageEditRequest, ImageEngineCapabilities
from app.video.runtime import detect_nvidia_gpu


FLUX3_SOURCE_REVISION = 'bfc8889a4497f846416f253a3972a1941ac698b9'
FLUX3_MODEL_ID = 'black-forest-labs/flux-3-image-klein'
FLUX3_PUP_ID = 'black-forest-labs/flux-3-image-klein-pup'
FLUX3_BF16_MIN_MB = 31 * 1024
FLUX3_FP8_MIN_MB = 26 * 1024
_SECRET_ENV_MARKERS = ('KEY', 'TOKEN', 'SECRET', 'PASSWORD')


@dataclass(frozen=True)
class FluxPythonProbe:
    available: bool
    cuda_available: bool
    detail: str


def _default_repo_dir() -> Path:
    return Path(os.getenv('CHARACTER3D_FLUX_REPO', './vendor/flux-3-image-klein')).expanduser()


def _default_weights_dir(repo_dir: Path) -> Path:
    explicit = os.getenv('CHARACTER3D_FLUX_WEIGHTS_DIR')
    return Path(explicit).expanduser() if explicit else repo_dir / 'weights'


def _default_python() -> str:
    return os.getenv('CHARACTER3D_FLUX_PYTHON', 'python')


def _timeout_seconds() -> int:
    raw = os.getenv('CHARACTER3D_FLUX_TIMEOUT_SECONDS', '1800')
    try:
        return max(120, min(24 * 3600, int(raw)))
    except ValueError:
        return 1800


def _sanitized_child_env(source: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(source or os.environ)
    for name in tuple(env):
        upper = name.upper()
        if any(marker in upper for marker in _SECRET_ENV_MARKERS):
            env.pop(name, None)
    env['HF_HUB_OFFLINE'] = '1'
    env['TRANSFORMERS_OFFLINE'] = '1'
    env['HF_HUB_DISABLE_TELEMETRY'] = '1'
    return env


def _fp8_capable_gpu(name: str) -> bool:
    normalized = name.upper()
    return any(token in normalized for token in (
        'RTX 40', 'RTX 50', 'L40', 'H100', 'H200', 'B100', 'B200', 'ADA', 'HOPPER', 'BLACKWELL'
    ))


def probe_flux_python(executable: str, repo_dir: Path) -> FluxPythonProbe:
    try:
        completed = subprocess.run(
            [executable, '-c', "import torch, flux3; print(int(torch.cuda.is_available()))"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
            shell=False,
            env=_sanitized_child_env(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return FluxPythonProbe(False, False, f'FLUX runtime unavailable: {exc.__class__.__name__}')
    if completed.returncode != 0:
        return FluxPythonProbe(False, False, 'Configured FLUX Python environment cannot import flux3')
    cuda_available = any(line.strip() == '1' for line in completed.stdout.splitlines())
    if not cuda_available:
        return FluxPythonProbe(False, False, 'Configured FLUX Python environment cannot access CUDA')
    return FluxPythonProbe(True, True, 'FLUX 3 Image Klein runtime ready')


class Flux3KleinLocalEngine:
    name = 'flux3_klein_local'

    def __init__(
        self,
        *,
        python_executable: str | None = None,
        repo_dir: str | Path | None = None,
        weights_dir: str | Path | None = None,
    ):
        self.repo_dir = Path(repo_dir).expanduser() if repo_dir else _default_repo_dir()
        self.python_executable = python_executable or _default_python()
        self.weights_dir = Path(weights_dir).expanduser() if weights_dir else _default_weights_dir(self.repo_dir)

    @property
    def cli_path(self) -> Path:
        return self.repo_dir / 'scripts' / 'cli.py'

    def _precision(self) -> str | None:
        gpu = detect_nvidia_gpu()
        if gpu is None:
            return None
        if gpu['total_mb'] >= FLUX3_BF16_MIN_MB:
            return 'bf16'
        if gpu['total_mb'] >= FLUX3_FP8_MIN_MB and _fp8_capable_gpu(gpu['name']):
            return 'fp8'
        return None

    def capabilities(self) -> ImageEngineCapabilities:
        problems: list[str] = []
        if not self.cli_path.is_file():
            problems.append('Pinned FLUX 3 Image Klein source checkout is missing')
        if not (self.weights_dir / 'flux-3-image-klein').is_dir():
            problems.append('FLUX 3 Image Klein weights are missing')
        if not (self.weights_dir / 'pup').is_dir():
            problems.append('FLUX prompt upsampler weights are missing')

        gpu = detect_nvidia_gpu()
        precision = self._precision()
        if gpu is None:
            problems.append('No NVIDIA GPU detected')
        elif precision is None:
            problems.append(
                'Official FLUX reference runner needs about 31 GiB VRAM in BF16 or 26 GiB on an FP8-capable GPU; '
                'smaller GPUs should use the int8 ComfyUI path.'
            )

        probe = probe_flux_python(self.python_executable, self.repo_dir) if self.cli_path.is_file() else None
        if probe is not None and not probe.available:
            problems.append(probe.detail)

        return ImageEngineCapabilities(
            name=self.name,
            available=not problems,
            supports_editing=True,
            precision=precision,
            min_vram_mb=(FLUX3_FP8_MIN_MB if precision == 'fp8' else FLUX3_BF16_MIN_MB),
            detail='; '.join(problems) if problems else (
                f'FLUX 3 Image Klein local edit runtime ready ({precision}, source {FLUX3_SOURCE_REVISION[:12]}).'
            ),
        )

    def build_command(self, request: ImageEditRequest, source_path: str | Path, output_path: str | Path) -> list[str]:
        precision = self._precision()
        command = [
            self.python_executable,
            str(self.cli_path),
            request.prompt,
            '--model', 'distilled',
            '--image', str(Path(source_path)),
            '--out', str(Path(output_path)),
            '--seed', str(request.seed),
        ]
        if precision == 'fp8':
            command.append('--fp8')
        return command

    def generate(self, *, request: ImageEditRequest, source_path: Path, output_path: Path, progress) -> Path:
        capabilities = self.capabilities()
        if not capabilities.available:
            raise RuntimeError(capabilities.detail)
        if not source_path.is_file():
            raise FileNotFoundError('Source image does not exist')

        output_path.parent.mkdir(parents=True, exist_ok=True)
        progress('generating', 15)
        env = _sanitized_child_env()
        env['WEIGHTS_DIR'] = str(self.weights_dir)
        sidecar = output_path.with_suffix('.json')
        try:
            completed = subprocess.run(
                self.build_command(request, source_path, output_path),
                cwd=str(self.repo_dir),
                capture_output=True,
                text=True,
                check=False,
                timeout=_timeout_seconds(),
                shell=False,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('FLUX 3 Image Klein generation exceeded the configured timeout') from exc
        except OSError as exc:
            raise RuntimeError('FLUX 3 Image Klein runtime could not be started') from exc
        finally:
            if sidecar.exists():
                try:
                    sidecar.unlink()
                except OSError:
                    pass

        if completed.returncode != 0:
            raise RuntimeError(f'FLUX 3 Image Klein generation failed with exit code {completed.returncode}')
        if not output_path.is_file():
            raise RuntimeError('FLUX 3 Image Klein completed without a PNG output')
        try:
            with Image.open(output_path) as image:
                if image.format != 'PNG':
                    raise RuntimeError('FLUX 3 Image Klein output is not PNG')
                image.verify()
        except OSError as exc:
            raise RuntimeError('FLUX 3 Image Klein output could not be validated') from exc
        progress('encoding', 95)
        return output_path
