from fastapi.testclient import TestClient
from app.main import app


def test_health_is_v12():
    r = TestClient(app).get('/health')
    assert r.status_code == 200
    assert r.json()['version'] == '1.5.0'


def test_build_fingerprint_endpoint():
    r = TestClient(app).get('/v1/release/build-fingerprint')
    assert r.status_code == 200
    payload = r.json()
    assert payload['fingerprint']['file_count'] > 0
    assert len(payload['fingerprint']['root_digest_sha256']) == 64
