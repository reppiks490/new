from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from app.image import engine
from app.image.models import ImageEditRequest

VALID_ID = "0123456789abcdef0123456789abcdef"


def _request(**changes):
    data = {"image_id": VALID_ID, "prompt": "make the jacket red", "seed": 7}
    data.update(changes)
    return ImageEditRequest(**data)


def test_select_image_engine_requires_available_local_engine():
    engine._ENGINE_REGISTRY.clear()
    with pytest.raises(engine.ImageEngineUnavailableError, match="No local image engine"):
        engine.select_engine()
    fake = engine.FakeImageEngine()
    engine.register_engine(fake)
    assert engine.select_engine() is fake


def test_fake_image_engine_edits_locally_and_preserves_png_contract(tmp_path):
    source = tmp_path / "source.png"
    output = tmp_path / "output.png"
    Image.new("RGB", (32, 24), (20, 40, 60)).save(source)
    progress = []

    result = engine.FakeImageEngine().generate(
        request=_request(),
        source_path=source,
        output_path=output,
        progress=lambda stage, value: progress.append((stage, value)),
    )

    assert result == output
    with Image.open(output) as image:
        assert image.format == "PNG"
        assert image.size == (32, 24)
    assert progress[0][0] == "generating"
    assert progress[-1][0] == "encoding"
