from pathlib import Path

import trimesh
from fastapi.testclient import TestClient

from app.main import app


def test_v09_health():
    c=TestClient(app)
    assert c.get('/health').json()['version']=='1.5.0'


def test_production_chain_auth_is_server_derived(monkeypatch):
    c=TestClient(app)
    monkeypatch.delenv('TRIPO_API_KEY',raising=False)
    r=c.post('/v1/pipeline/production-chain-plan',json={'job_id':'j1','provider':'tripo'})
    assert r.status_code==200 and r.json()['blockers']
    monkeypatch.setenv('TRIPO_API_KEY','test-secret')
    r=c.post('/v1/pipeline/production-chain-plan',json={'job_id':'j1','provider':'tripo'})
    assert r.status_code==200 and not r.json()['blockers']


def test_job_claim_api_retry(tmp_path: Path,monkeypatch):
    monkeypatch.setenv('CHARACTER3D_CLAIM_DB',str(tmp_path/'claims.db'))
    c=TestClient(app)
    assert c.post('/v1/runtime/jobs/enqueue',json={'job_id':'x'}).status_code==200
    r=c.post('/v1/runtime/jobs/claim',json={'job_id':'x','owner_id':'w','ttl_seconds':30}); assert r.status_code==200
    token=r.json()['token']
    r=c.post('/v1/runtime/jobs/fail',json={'job_id':'x','token':token,'retryable':False,'error':'fatal'}); assert r.status_code==200
    assert r.json()['state']=='failed'


def test_animated_groom_api(tmp_path: Path):
    body=trimesh.creation.box(extents=[2,2,2]); p=tmp_path/'b.ply'; body.export(p)
    c=TestClient(app)
    payload={'body_mesh':str(p),'samples':[{'frame':1,'strands':[[[0,0,1.2],[0,0,1.1]]]}]}
    r=c.post('/v1/qa/groom-collisions/animated',json=payload)
    assert r.status_code==200 and r.json()['frame_count']==1
