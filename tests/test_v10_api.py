from fastapi.testclient import TestClient
from app.main import app


def _evidence(mode='live'):
    return [
        {'stage':stage,'mode':mode,'success':True,'tool':'test','started_at':1,'finished_at':2}
        for stage in ['provider_ingest','candidate_promotion','blender','qa','export']
    ]


def test_v10_health_and_readiness():
    c=TestClient(app)
    assert c.get('/health').json()['version']=='1.5.0'
    r=c.get('/v1/runtime/readiness')
    assert r.status_code==200 and 'blender' in r.json() and 'providers' in r.json()


def test_release_evaluate_api_rejects_synthetic_critical_stages():
    c=TestClient(app)
    r=c.post('/v1/release/evaluate',json={'evidence':_evidence('synthetic'),'production_gate_passed':True})
    assert r.status_code==200 and not r.json()['releasable']


def test_release_manifest_api_fixed_timestamp_is_reproducible():
    c=TestClient(app)
    payload={
        'job_id':'j1',
        'artifacts':[{'name':'a.glb','kind':'model','size_bytes':1,'sha256':'a'*64}],
        'evidence':_evidence('live'),
        'production_gate_passed':True,
        'created_at_unix':123,
    }
    a=c.post('/v1/release/canonical-manifest',json=payload)
    b=c.post('/v1/release/canonical-manifest',json=payload)
    assert a.status_code==200 and a.json()['releasable'] and a.json()['manifest_sha256']==b.json()['manifest_sha256']
