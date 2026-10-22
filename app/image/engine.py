from __future__ import annotations

from pathlib import Path
from typing import Callable, Protocol

from PIL import Image

from app.image.models import ImageEditRequest, ImageEngineCapabilities


ProgressCallback = Callable[[str, int], None]


class ImageEngineUnavailableError(RuntimeError):
    pass


class ImageToImageEngine(Protocol):
    name: str

    def capabilities(self) -> ImageEngineCapabilities: ...

    def generate(
        self,
        *,
        request: ImageEditRequest,
        source_path: Path,
        output_path: Path,
        progress: ProgressCallback,
    ) -> Path: ...


_ENGINE_REGISTRY: dict[str, ImageToImageEngine] = {}


def _ensure_builtin_engines() -> None:
    if 'flux3_klein_local' not in _ENGINE_REGISTRY:
        from app.image.adapters.flux3_klein import Flux3KleinLocalEngine
        register_engine(Flux3KleinLocalEngine())


def register_engine(engine: ImageToImageEngine, *, replace: bool = False) -> None:
    if not engine.name or (engine.name in _ENGINE_REGISTRY and not replace):
        raise ValueError(f'Image engine {engine.name!r} is already registered or invalid')
    _ENGINE_REGISTRY[engine.name] = engine


def get_engine(name: str) -> ImageToImageEngine:
    try:
        return _ENGINE_REGISTRY[name]
    except KeyError as exc:
        raise ImageEngineUnavailableError(f'Local image engine {name!r} is not registered') from exc


def registered_image_engine_capabilities() -> list[ImageEngineCapabilities]:
    _ensure_builtin_engines()
    return [engine.capabilities() for engine in _ENGINE_REGISTRY.values()]


def select_engine() -> ImageToImageEngine:
    _ensure_builtin_engines()
    for image_engine in _ENGINE_REGISTRY.values():
        if image_engine.capabilities().available:
            return image_engine
    raise ImageEngineUnavailableError('No local image engine is currently available')


class FakeImageEngine:
    """Deterministic local image engine for API and queue tests."""

    name = 'fake_image'

    def capabilities(self) -> ImageEngineCapabilities:
        return ImageEngineCapabilities(
            name=self.name,
            available=True,
            supports_editing=True,
            precision='fixture',
            detail='Deterministic local PNG fixture engine; not a production generative model.',
        )

    def generate(
        self,
        *,
        request: ImageEditRequest,
        source_path: Path,
        output_path: Path,
        progress: ProgressCallback,
    ) -> Path:
        if not source_path.is_file():
            raise FileNotFoundError('Source image does not exist')
        progress('generating', 25)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(source_path) as image:
            image.convert('RGB').save(output_path, format='PNG')
        progress('encoding', 90)
        return output_path
