from pathlib import Path
from fastapi.testclient import TestClient
import trimesh
from app.main import app


def test_v08_health_and_bake_contract():
    c=TestClient(app)
    assert c.get('/health').json()['version']=='1.2.0'
    r=c.post('/v1/blender/high-low-bake-contract',json={'high_mesh':'hi.glb','low_mesh':'lo.glb','cage_mesh':'cage.glb','extreme':True})
    assert r.status_code==200 and not r.json()['blockers'] and r.json()['resolution']==8192


def test_v08_exact_endpoint(tmp_path: Path):
    mesh=trimesh.Trimesh(vertices=[[0,0,0],[1,0,0],[0,1,0],[.25,.25,-1],[.25,.25,1],[.75,.25,0]],faces=[[0,1,2],[3,4,5]],process=False)
    p=tmp_path/'x.ply'; mesh.export(p)
    c=TestClient(app); r=c.post('/v1/qa/exact-intersections',json={'path':str(p)})
    assert r.status_code==200 and r.json()['report']['intersecting_pair_count']==1


def test_v08_rig_and_identity_region_endpoints():
    c=TestClient(app)
    r=c.post('/v1/qa/rig-weights',json={'vertices':[{'influences':{'hip':1.0}}],'known_bones':['hip']})
    assert r.status_code==200 and r.json()['passed']
    payload={'reference':[[0,0],[1,0],[0,1]],'candidate':[[0,0],[1,0],[0,1]],'regions':[{'name':'face','indices':[0,1,2],'weight':2}]}
    r=c.post('/v1/qa/identity-regions',json=payload)
    assert r.status_code==200 and r.json()['weighted_similarity']>0.999
