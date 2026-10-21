from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from app.video.models import EngineCapabilities, VideoGenerationRequest

VALID_ID = "0123456789abcdef0123456789abcdef"


def _request(**changes):
    data = {
        "image_id": VALID_ID,
        "prompt": "subtle breathing and a slow camera push",
        "engine_profile": "balanced",
        "seed": 123,
        "duration_seconds": 2,
        "fps": 24,
        "resolution": "720p",
    }
    data.update(changes)
    return VideoGenerationRequest(**data)


def test_select_engine_requires_registered_available_profile():
    from app.video import engine

    engine._ENGINE_REGISTRY.clear()
    with pytest.raises(engine.EngineUnavailableError, match="No local video engine"):
        engine.select_engine("balanced")

    fake = engine.FakeVideoEngine()
    engine.register_engine(fake)
    assert engine.select_engine("balanced") is fake


def test_request_validation_rejects_controls_engine_does_not_support():
    from app.video import engine

    capabilities = EngineCapabilities(
        name="limited",
        available=True,
        profiles=["balanced"],
        supported_resolutions=["720p"],
        min_duration_seconds=1,
        max_duration_seconds=5,
        supported_fps=[24],
        supports_motion_strength=False,
        camera_motion_presets=["static"],
    )

    with pytest.raises(engine.UnsupportedEngineControl, match="motion_strength"):
        engine.validate_request_for_engine(_request(motion_strength=0.5), capabilities)
    with pytest.raises(engine.UnsupportedEngineControl, match="camera_motion"):
        engine.validate_request_for_engine(_request(camera_motion="zoom_in"), capabilities)
    with pytest.raises(engine.UnsupportedEngineControl, match="resolution"):
        engine.validate_request_for_engine(_request(resolution="1080p"), capabilities)


def test_fake_engine_generates_hermetic_mp4_fixture_without_external_encoder(monkeypatch, tmp_path):
    from app.video import engine

    source = tmp_path / "source.png"
    output = tmp_path / "out.mp4"
    Image.new("RGB", (48, 32), (40, 80, 120)).save(source)
    progress = []
    monkeypatch.setenv("PATH", "")

    result = engine.FakeVideoEngine().generate(
        request=_request(),
        source_path=source,
        output_path=output,
        progress=lambda stage, value: progress.append((stage, value)),
    )

    assert result == output
    payload = output.read_bytes()
    assert len(payload) > 500
    assert b"ftyp" in payload[:64]
    assert b"moov" in payload
    assert b"mdat" in payload
    assert progress == [("generating", 25), ("encoding", 90)]
