import pytest
from PIL import Image

from app.video.models import VideoGenerationRequest
from app.video.storage import video_asset_path
from app.video import engine


def make_source(tmp_path, monkeypatch):
    monkeypatch.setenv('CHARACTER3D_STUDIO_WORKSPACE', str(tmp_path))
    ident = '1' * 32
    Image.new('RGB', (32, 24), 'white').save(video_asset_path(ident, 'png'))
    return ident


def test_fake_engine_emits_mp4(tmp_path, monkeypatch):
    ident = make_source(tmp_path, monkeypatch)
    request = VideoGenerationRequest(image_id=ident, prompt='gentle motion')
    output = video_asset_path('2'*32, 'mp4')
    fake = engine.FakeVideoEngine()
    seen = []
    result = fake.generate(request, video_asset_path(ident, 'png'), output, lambda stage, progress: seen.append((stage, progress)))
    assert result == output
    data = output.read_bytes()
    assert len(data) > 1000
    assert b'ftyp' in data[:32]
    assert any(stage == 'encoding' for stage, _ in seen)


def test_engine_rejects_unsupported_controls():
    fake = engine.FakeVideoEngine()
    request = VideoGenerationRequest(image_id='3'*32, prompt='move', motion_strength=0.5)
    with pytest.raises(ValueError, match='motion_strength'):
        engine.validate_engine_request(request, fake.capabilities())


def test_engine_registry_selects_only_local_registered_engine():
    engine.clear_engines()
    assert engine.select_engine('auto') is None
    engine.register_engine('fake', engine.FakeVideoEngine)
    selected = engine.select_engine('auto')
    assert isinstance(selected, engine.FakeVideoEngine)
    assert selected.capabilities().name == 'fake'
