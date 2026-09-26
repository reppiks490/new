from pathlib import Path

import numpy as np
from PIL import Image
import trimesh

from app.exports.validation import validate_export
from app.qa.identity import compare_landmarks
from app.qa.repair import apply_conservative_repairs, compile_repair_plan
from app.qa.specialized import EyeQAInput, GroomQAInput, SkinQAInput, qa_eyes, qa_groom, qa_skin
from app.render.multiview import compare_multiview, compare_rendered_view
from app.runtime.gpu_scheduler import GPUJobRequest, GPUWorker, choose_gpu_worker


def test_identity_is_invariant_to_translation_rotation_scale():
    ref=np.array([[0,0],[1,0],[1,1],[0,1],[.5,.3]],float)
    theta=np.deg2rad(37)
    r=np.array([[np.cos(theta),-np.sin(theta)],[np.sin(theta),np.cos(theta)]])
    cand=ref @ r.T * 2.5 + np.array([9.0,-4.0])
    report=compare_landmarks(ref,cand)
    assert report.similarity > 0.999999
    assert report.normalized_rms_error < 1e-6


def test_identity_penalizes_local_shape_change():
    ref=np.array([[0,0],[1,0],[1,1],[0,1],[.5,.3]],float)
    cand=ref.copy(); cand[4]=[.5,1.8]
    report=compare_landmarks(ref,cand)
    assert report.similarity < 0.85
    assert report.warnings


def test_repair_removes_degenerate_face(tmp_path: Path):
    mesh=trimesh.Trimesh(vertices=[[0,0,0],[1,0,0],[0,1,0],[2,2,2]],faces=[[0,1,2],[0,0,1]],process=False)
    src=tmp_path/'broken.obj'; dst=tmp_path/'repaired.obj'; mesh.export(src)
    plan=compile_repair_plan(src)
    assert any(a.action=='remove_degenerate_faces' for a in plan.actions)
    receipt=apply_conservative_repairs(src,dst)
    assert receipt.after.degenerate_face_count == 0
    assert receipt.after.face_count < receipt.before.face_count
    assert receipt.source_sha256 != '' and receipt.output_sha256 != ''


def test_specialized_qa_separates_subsystems():
    skin=qa_skin(SkinQAInput(has_micro_normal=True,has_sss_profile=True,displacement_bits=32,texture_resolution=8192))
    eye=qa_eyes(EyeQAInput(has_tearline=True,cornea_ior=1.376,iris_depth_mm=.45))
    groom=qa_groom(GroomQAInput(strand_count=120_000,guide_count=2500,root_coverage=.98,mean_segments_per_strand=8,scalp_binding=True,has_clump_profile=True))
    assert skin.passed and eye.passed and groom.passed
    bad=qa_groom(GroomQAInput(strand_count=1000,guide_count=10,root_coverage=.5,mean_segments_per_strand=2,scalp_binding=False))
    assert not bad.passed and bad.blockers


def test_multiview_similarity_identical_and_changed(tmp_path: Path):
    a=np.tile(np.linspace(0,255,64,dtype=np.uint8),(64,1))
    p1=tmp_path/'a.png'; p2=tmp_path/'b.png'; p3=tmp_path/'c.png'
    Image.fromarray(a).save(p1); Image.fromarray(a).save(p2); Image.fromarray(255-a).save(p3)
    identical=compare_rendered_view(p1,p2)
    changed=compare_rendered_view(p1,p3)
    assert identical.combined_similarity > 0.999
    assert changed.combined_similarity < identical.combined_similarity
    multi=compare_multiview([p1,p1],[p2,p3])
    assert multi.mean_similarity < 1 and len(multi.views)==2


def test_export_validation_for_obj_and_glb(tmp_path: Path):
    mesh=trimesh.creation.icosphere(subdivisions=1)
    obj=tmp_path/'hero.obj'; glb=tmp_path/'hero.glb'
    mesh.export(obj); mesh.export(glb)
    ro=validate_export(obj); rg=validate_export(glb)
    assert ro.passed and rg.passed
    assert ro.face_count > 0 and rg.face_count > 0


def test_gpu_scheduler_prefers_backend_and_headroom():
    workers=[
        GPUWorker(worker_id='a',vendor='nvidia',backend='OPTIX',total_vram_gb=24,free_vram_gb=18,queue_depth=2,capabilities={'cycles','bake'}),
        GPUWorker(worker_id='b',vendor='nvidia',backend='OPTIX',total_vram_gb=48,free_vram_gb=30,queue_depth=1,capabilities={'cycles','bake'}),
        GPUWorker(worker_id='c',vendor='amd',backend='HIP',total_vram_gb=48,free_vram_gb=40,queue_depth=0,capabilities={'cycles'}),
    ]
    req=GPUJobRequest(min_vram_gb=16,preferred_backend='OPTIX',required_capabilities={'cycles','bake'},reserve_vram_gb=4)
    decision=choose_gpu_worker(workers,req)
    assert decision.worker.worker_id=='b'

from fastapi.testclient import TestClient
from app.main import app
from app.providers.attestation import attest_file, verify_file_attestation
from app.workers.blender_pipeline import compile_blender_production_manifest


def test_hmac_attestation_detects_change(tmp_path: Path):
    p=tmp_path/'artifact.bin'; p.write_bytes(b'abc')
    secret='0123456789abcdef0123456789abcdef'
    env=attest_file(p,secret,key_id='test')
    assert verify_file_attestation(p,env,secret)
    p.write_bytes(b'abd')
    assert not verify_file_attestation(p,env,secret)


def test_blender_production_manifest_extreme():
    m=compile_blender_production_manifest('hero.glb','workspace',vram_gb=48,render_mode='extreme',udim_tiles=[1001,1002],resolution=8192,export_formats=['glb','usd'])
    assert m.render_preset.samples >= 1024
    assert m.bake_plan.resolution==8192
    assert {x.format for x in m.export_targets}=={'glb','usd'}


def test_api_v07_health_and_identity():
    client=TestClient(app)
    assert client.get('/health').json()['version']=='1.4.0'
    payload={'reference':[[0,0],[1,0],[0,1]],'candidate':[[5,5],[7,5],[5,7]]}
    r=client.post('/v1/qa/identity',json=payload)
    assert r.status_code==200 and r.json()['similarity']>0.999
