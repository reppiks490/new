import io

from fastapi.testclient import TestClient
from PIL import Image


def png_bytes(size=(32, 24)):
    out = io.BytesIO()
    Image.new('RGB', size, 'white').save(out, format='PNG')
    return out.getvalue()


def client(monkeypatch, tmp_path, token=None):
    monkeypatch.setenv('CHARACTER3D_STUDIO_WORKSPACE', str(tmp_path))
    if token is None:
        monkeypatch.delenv('CHARACTER3D_STUDIO_TOKEN', raising=False)
    else:
        monkeypatch.setenv('CHARACTER3D_STUDIO_TOKEN', token)
    from app.studio.server import app
    return TestClient(app)


def test_video_capabilities_and_existing_studio_route(monkeypatch, tmp_path):
    c = client(monkeypatch, tmp_path)
    r = c.get('/api/video/capabilities')
    assert r.status_code == 200
    assert 'available' in r.json()
    assert c.get('/api/studio/capabilities').status_code == 200


def test_image_upload_normalizes_png(monkeypatch, tmp_path):
    c = client(monkeypatch, tmp_path)
    r = c.post('/api/video/images', files={'file': ('source.webp', png_bytes(), 'image/webp')})
    assert r.status_code == 200
    body = r.json()
    assert len(body['image_id']) == 32
    from app.video.storage import video_asset_path
    saved = Image.open(video_asset_path(body['image_id'], 'png'))
    assert saved.mode == 'RGB'


def test_image_upload_rejects_invalid_and_oversized(monkeypatch, tmp_path):
    c = client(monkeypatch, tmp_path)
    assert c.post('/api/video/images', files={'file': ('x.txt', b'nope', 'text/plain')}).status_code == 422
    too_big = b'x' * (12*1024*1024 + 1)
    assert c.post('/api/video/images', files={'file': ('x.png', too_big, 'image/png')}).status_code == 413


def test_api_requires_configured_token(monkeypatch, tmp_path):
    c = client(monkeypatch, tmp_path, token='secret-value')
    assert c.get('/api/video/capabilities').status_code == 401
    assert c.get('/api/video/capabilities', headers={'Authorization': 'Bearer wrong'}).status_code == 401
    assert c.get('/api/video/capabilities', headers={'Authorization': 'Bearer secret-value'}).status_code == 200


def test_mp4_asset_content_type(monkeypatch, tmp_path):
    c = client(monkeypatch, tmp_path)
    from app.video.storage import video_asset_path
    ident = 'd'*32
    video_asset_path(ident, 'mp4').write_bytes(b'fake-mp4')
    r = c.get(f'/api/video/assets/{ident}.mp4')
    assert r.status_code == 200
    assert r.headers['content-type'].startswith('video/mp4')


def test_privacy_get_put_validates(monkeypatch, tmp_path):
    c = client(monkeypatch, tmp_path)
    r = c.get('/api/video/privacy')
    assert r.status_code == 200
    assert r.json()['privacy_mode'] is True
    r = c.put('/api/video/privacy', json={'privacy_mode': False, 'idle_lock_seconds': 45})
    assert r.status_code == 200
    assert r.json()['privacy_mode'] is False
    assert r.json()['idle_lock_seconds'] == 45
    assert c.put('/api/video/privacy', json={'idle_lock_seconds': 0}).status_code == 422


def test_jobs_missing_returns_404(monkeypatch, tmp_path):
    c = client(monkeypatch, tmp_path)
    assert c.get('/api/video/jobs/' + 'e'*32).status_code == 404
