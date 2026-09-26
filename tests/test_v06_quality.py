from pathlib import Path
import numpy as np
from PIL import Image
import trimesh

from app.qa.pbr import inspect_pbr_map, infer_map_kind
from app.qa.uv import inspect_uv
from app.providers.chain import ProvenanceChain
from app.render.cycles import quality_preset
from app.runtime.resume import decide_resume
from app.providers.ledger import ProviderLedger
from app.providers.execution import ProviderTaskSnapshot, CanonicalTaskStatus, RemoteAsset
from app.providers.models import ProviderId


def test_pbr_semantics_and_16bit_warning(tmp_path: Path):
    p=tmp_path/'skin_displacement.1001.png'
    Image.fromarray(np.arange(64,dtype=np.uint8).reshape(8,8)).save(p)
    r=inspect_pbr_map(p)
    assert r.kind=='displacement' and r.inferred_udim==1001 and r.expected_color_space=='Non-Color'
    assert any('16-bit' in w for w in r.warnings)
    assert infer_map_kind('hero_BaseColor_1001.png')=='basecolor'


def test_uv_report(tmp_path: Path):
    mesh=trimesh.Trimesh(vertices=[[0,0,0],[1,0,0],[1,1,0],[0,1,0]], faces=[[0,1,2],[0,2,3]], process=False)
    mesh.visual=trimesh.visual.TextureVisuals(uv=np.array([[0,0],[1,0],[1,1],[0,1]],float))
    p=tmp_path/'quad.obj'; mesh.export(p)
    r=inspect_uv(p)
    assert r.face_count==2 and r.tile_count>=1 and r.finite_ratio==1


def test_provenance_chain_detects_tamper(tmp_path: Path):
    p=tmp_path/'chain.jsonl'; c=ProvenanceChain(p)
    c.append('provider_ingest', artifact_sha256='a'*64)
    c.append('canonical_promotion', artifact_sha256='b'*64)
    assert c.verify()
    raw=p.read_text(); p.write_text(raw.replace('canonical_promotion','canonical_promotioX'))
    assert not c.verify()


def test_cycles_profiles_scale():
    preview=quality_preset(12,mode='preview'); hero=quality_preset(48,mode='hero')
    assert hero.samples > preview.samples and hero.subdivision_dicing_rate < preview.subdivision_dicing_rate


def test_resume_decisions(tmp_path: Path):
    ledger=ProviderLedger(tmp_path/'ledger.sqlite')
    assert decide_resume(ledger,ProviderId.TRIPO,'x').action=='submit'
    snap=ProviderTaskSnapshot(provider=ProviderId.TRIPO,task_id='x',status=CanonicalTaskStatus.RUNNING,raw_status='running')
    ledger.upsert_snapshot(snap); assert decide_resume(ledger,ProviderId.TRIPO,'x').action=='poll'
    done=ProviderTaskSnapshot(provider=ProviderId.TRIPO,task_id='x',status=CanonicalTaskStatus.SUCCEEDED,raw_status='success',assets=[RemoteAsset(kind='model',url='https://example.com/a.glb')])
    ledger.upsert_snapshot(done); assert decide_resume(ledger,ProviderId.TRIPO,'x').action=='ingest'

from app.qa.self_intersection import localize_self_intersection_candidates
from app.materials.bake import compile_udim_bake_plan

def test_intersection_broadphase_clean_quad(tmp_path: Path):
    mesh=trimesh.Trimesh(vertices=[[0,0,0],[1,0,0],[1,1,0],[0,1,0]], faces=[[0,1,2],[0,2,3]], process=False)
    p=tmp_path/'clean.obj'; mesh.export(p)
    r=localize_self_intersection_candidates(p)
    assert r.face_count==2 and r.suspicious_face_count==0


def test_udim_bake_plan_hero():
    p=compile_udim_bake_plan([1002,1001],resolution=8192,hero=True)
    assert p.tiles==[1001,1002] and p.estimated_raw_gib>0
    disp=next(x for x in p.passes if x.map_kind=='displacement')
    assert disp.bit_depth==32 and disp.color_space=='Non-Color'
