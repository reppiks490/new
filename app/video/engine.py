from __future__ import annotations

import base64
from pathlib import Path
from typing import Callable, Protocol

from app.video.models import EngineCapabilities, VideoGenerationRequest


ProgressCallback = Callable[[str, int], None]


class ImageToVideoEngine(Protocol):
    name: str

    def capabilities(self) -> EngineCapabilities: ...

    def generate(
        self,
        request: VideoGenerationRequest,
        source_image: Path,
        output_path: Path,
        progress: ProgressCallback,
    ) -> Path: ...


_ENGINE_FACTORIES: dict[str, Callable[[], ImageToVideoEngine]] = {}


def register_engine(name: str, factory: Callable[[], ImageToVideoEngine]) -> None:
    if not name or not callable(factory):
        raise ValueError('Engine registration requires a name and callable factory')
    _ENGINE_FACTORIES[name] = factory


def clear_engines() -> None:
    _ENGINE_FACTORIES.clear()


def select_engine(profile: str) -> ImageToVideoEngine | None:
    for factory in _ENGINE_FACTORIES.values():
        instance = factory()
        caps = instance.capabilities()
        if not caps.available:
            continue
        if profile == 'auto' or profile in caps.profiles:
            return instance
    return None


def validate_engine_request(request: VideoGenerationRequest, caps: EngineCapabilities) -> None:
    if request.resolution not in caps.resolutions:
        raise ValueError(f'resolution {request.resolution} is unsupported by {caps.name}')
    if not (caps.min_duration_seconds <= request.duration_seconds <= caps.max_duration_seconds):
        raise ValueError(f'duration_seconds is unsupported by {caps.name}')
    if not (caps.min_fps <= request.fps <= caps.max_fps):
        raise ValueError(f'fps is unsupported by {caps.name}')
    if request.motion_strength is not None and not caps.supports_motion_strength:
        raise ValueError(f'motion_strength is unsupported by {caps.name}')
    if request.camera_motion is not None and not caps.supports_camera_motion:
        raise ValueError(f'camera_motion is unsupported by {caps.name}')


_TINY_MP4_B64 = (
    'AAAAIGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDEAAAMUbW9vdgAAAGxtdmhkAAAAAAAAAAAAAAAAAAAD6AAAACgAAQAAAQAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAAAj90cmFrAAAAXHRraGQAAAADAAAAAAAAAAAAAAABAAAAAAAAACgAAAAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAABAAAAAQAAAAAAAkZWR0cwAAABxlbHN0AAAAAAAAAAEAAAAoAAAAAAABAAAAAAG3bWRpYQAAACBtZGhkAAAAAAAAAAAAAAAAAAAyAAAAAgBVxAAAAAAALWhkbHIAAAAAAAAAAHZpZGUAAAAAAAAAAAAAAABWaWRlb0hhbmRsZXIAAAABYm1pbmYAAAAUdm1oZAAAAAEAAAAAAAAAAAAAACRkaW5mAAAAHGRyZWYAAAAAAAAAAQAAAAx1cmwgAAAAAQAAASJzdGJsAAAAvnN0c2QAAAAAAAAAAQAAAK5hdmMxAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAAABAAEABIAAAASAAAAAAAAAABFUxhdmM2MS4xOS4xMDEgbGlieDI2NAAAAAAAAAAAAAAAGP//AAAANGF2Y0MBZAAK/+EAF2dkAAqs2V7ARAAAAwAEAAADAMg8SJZYAQAGaOvjyyLA/fj4AAAAABBwYXNwAAAAAQAAAAEAAAAUYnRydAAAAAAAAinoAAAAAAAAABhzdHRzAAAAAAAAAAEAAAABAAACAAAAABxzdHNjAAAAAAAAAAEAAAABAAAAAQAAAAEAAAAUc3RzegAAAAAAAALFAAAAAQAAABRzdGNvAAAAAAAAAAEAAANEAAAAYXVkdGEAAABZbWV0YQAAAAAAAAAhaGRscgAAAAAAAAAAbWRpcmFwcGwAAAAAAAAAAAAAAAAsaWxzdAAAACSpdG9vAAAAHGRhdGEAAAABAAAAAExhdmY2MS43LjEwMwAAAAhmcmVlAAACzW1kYXQAAAKuBgX//6rcRem95tlIt5Ys2CDZI+7veDI2NCAtIGNvcmUgMTY0IHIzMTA4IDMxZTE5ZjkgLSBILjI2NC9NUEVHLTQgQVZDIGNvZGVjIC0gQ29weWxlZnQgMjAwMy0yMDIzIC0gaHR0cDovL3d3dy52aWRlb2xhbi5vcmcveDI2NC5odG1sIC0gb3B0aW9uczogY2FiYWM9MSByZWY9MyBkZWJsb2NrPTE6MDowIGFuYWx5c2U9MHgzOjB4MTEzIG1lPWhleCBzdWJtZT03IHBzeT0xIHBzeV9yZD0xLjAwOjAuMDAgbWl4ZWRfcmVmPTEgbWVfcmFuZ2U9MTYgY2hyb21hX21lPTEgdHJlbGxpcz0xIDh4OGRjdD0xIGNxbT0wIGRlYWR6b25lPTIxLDExIGZhc3RfcHNraXA9MSBjaHJvbWFfcXBfb2Zmc2V0PS0yIHRocmVhZHM9MSBsb29rYWhlYWRfdGhyZWFkcz0xIHNsaWNlZF90aHJlYWRzPTAgbnI9MCBkZWNpbWF0ZT0xIGludGVybGFjZWQ9MCBibHVyYXlfY29tcGF0PTAgY29uc3RyYWluZWRfaW50cmE9MCBiZnJhbWVzPTMgYl9weXJhbWlkPTIgYl9hZGFwdD0xIGJfYmlhcz0wIGRpcmVjdD0xIHdlaWdodGI9MSBvcGVuX2dvcD0wIHdlaWdodHA9MiBrZXlpbnQ9MjUwIGtleWludF9taW49MjUgc2NlbmVjdXQ9NDAgaW50cmFfcmVmcmVzaD0wIHJjX2xvb2thaGVhZD00MCByYz1jcmYgbWJ0cmVlPTEgY3JmPTIzLjAgcWNvbXA9MC42MCBxcG1pbj0wIHFwbWF4PTY5IHFwc3RlcD00IGlwX3JhdGlvPTEuNDAgYXE9MToxLjAwAIAAAAAPZYiEACv//vZzfAprbbGB'
)


class FakeVideoEngine:
    name = 'fake'

    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            name=self.name,
            available=True,
            profiles=['auto', 'low_vram', 'balanced', 'high_quality'],
            resolutions=['480p', '720p', '1080p'],
            min_duration_seconds=1,
            max_duration_seconds=12,
            min_fps=1,
            max_fps=60,
            supports_motion_strength=False,
            supports_camera_motion=False,
            detail='Deterministic local test engine; not a production generator.',
        )

    def generate(
        self,
        request: VideoGenerationRequest,
        source_image: Path,
        output_path: Path,
        progress: ProgressCallback,
    ) -> Path:
        if not source_image.is_file():
            raise FileNotFoundError(source_image)
        validate_engine_request(request, self.capabilities())
        progress('generating', 40)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        progress('encoding', 85)
        output_path.write_bytes(base64.b64decode(_TINY_MP4_B64))
        return output_path
