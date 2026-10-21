from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Callable, Protocol

from app.video.models import EngineCapabilities, EngineProfile, VideoGenerationRequest


ProgressCallback = Callable[[str, int], None]


class EngineUnavailableError(RuntimeError):
    pass


class UnsupportedEngineControl(ValueError):
    pass


class ImageToVideoEngine(Protocol):
    name: str

    def capabilities(self) -> EngineCapabilities: ...

    def generate(
        self,
        *,
        request: VideoGenerationRequest,
        source_path: Path,
        output_path: Path,
        progress: ProgressCallback,
    ) -> Path: ...


_ENGINE_REGISTRY: dict[str, ImageToVideoEngine] = {}


def _ensure_builtin_engines() -> None:
    if 'ltx25_local' not in _ENGINE_REGISTRY:
        from app.video.adapters.ltx25 import Ltx25LocalEngine
        register_engine(Ltx25LocalEngine())


def register_engine(engine: ImageToVideoEngine, *, replace: bool = False) -> None:
    if not engine.name or (engine.name in _ENGINE_REGISTRY and not replace):
        raise ValueError(f'Video engine {engine.name!r} is already registered or invalid')
    _ENGINE_REGISTRY[engine.name] = engine


def get_engine(name: str) -> ImageToVideoEngine:
    try:
        return _ENGINE_REGISTRY[name]
    except KeyError as exc:
        raise EngineUnavailableError(f'Local video engine {name!r} is not registered') from exc


def registered_engine_capabilities() -> list[EngineCapabilities]:
    _ensure_builtin_engines()
    return [engine.capabilities() for engine in _ENGINE_REGISTRY.values()]


def select_engine(profile: EngineProfile) -> ImageToVideoEngine:
    _ensure_builtin_engines()
    for engine in _ENGINE_REGISTRY.values():
        capabilities = engine.capabilities()
        if capabilities.available and profile in capabilities.profiles:
            return engine
    raise EngineUnavailableError(f'No local video engine is available for profile {profile!r}')


def validate_request_for_engine(request: VideoGenerationRequest, capabilities: EngineCapabilities) -> None:
    if request.engine_profile not in capabilities.profiles:
        raise UnsupportedEngineControl(f'engine_profile {request.engine_profile!r} is not supported by {capabilities.name}')
    if request.resolution not in capabilities.supported_resolutions:
        raise UnsupportedEngineControl(f'resolution {request.resolution!r} is not supported by {capabilities.name}')
    if not capabilities.min_duration_seconds <= request.duration_seconds <= capabilities.max_duration_seconds:
        raise UnsupportedEngineControl(
            f'duration_seconds must be between {capabilities.min_duration_seconds} and '
            f'{capabilities.max_duration_seconds} for {capabilities.name}'
        )
    if capabilities.supported_fps and request.fps not in capabilities.supported_fps:
        raise UnsupportedEngineControl(f'fps {request.fps} is not supported by {capabilities.name}')
    if request.motion_strength is not None and not capabilities.supports_motion_strength:
        raise UnsupportedEngineControl(f'motion_strength is not supported by {capabilities.name}')
    if request.camera_motion is not None and request.camera_motion not in capabilities.camera_motion_presets:
        raise UnsupportedEngineControl(f'camera_motion {request.camera_motion!r} is not supported by {capabilities.name}')


class FakeVideoEngine:
    """Deterministic local-only engine used for tests and explicit development mode."""

    name = 'fake'

    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            name=self.name,
            available=True,
            profiles=['low_vram', 'balanced', 'high_quality'],
            supported_resolutions=['480p', '720p', '1080p'],
            min_duration_seconds=1,
            max_duration_seconds=30,
            supported_fps=[8, 12, 24, 30, 60],
            supports_motion_strength=False,
            camera_motion_presets=['static'],
            detail='Deterministic local FFmpeg test engine; not a production generative model.',
        )

    def generate(
        self,
        *,
        request: VideoGenerationRequest,
        source_path: Path,
        output_path: Path,
        progress: ProgressCallback,
    ) -> Path:
        validate_request_for_engine(request, self.capabilities())
        if not source_path.is_file():
            raise FileNotFoundError('Source image does not exist')
        output_path.parent.mkdir(parents=True, exist_ok=True)
        progress('generating', 25)
        completed = subprocess.run(
            [
                'ffmpeg', '-y', '-loglevel', 'error',
                '-loop', '1', '-i', str(source_path),
                '-t', '0.25', '-vf', 'scale=64:64', '-r', '8', '-an',
                '-c:v', 'mpeg4', '-q:v', '5', '-movflags', '+faststart',
                str(output_path),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        if completed.returncode != 0:
            raise RuntimeError(f'FFmpeg test encoding failed: {(completed.stderr or "unknown error")[-500:]}')
        progress('encoding', 90)
        return output_path
