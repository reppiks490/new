from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.release.canonical import (
    CanonicalArtifact,
    artifact_from_path,
    compile_canonical_release_manifest,
    evaluate_canonical_release,
    verify_canonical_manifest,
)
from app.runtime.capabilities import detect_runtime_readiness
from app.workers.blender import BlenderInvocation
from app.workers.execution_evidence import ExecutionEvidence, ExecutionMode, execute_blender_with_receipt


def _ev(stage: str, mode: ExecutionMode = ExecutionMode.LIVE, success: bool = True) -> ExecutionEvidence:
    return ExecutionEvidence(stage=stage, mode=mode, success=success, tool='test', started_at=1, finished_at=2)


def test_canonical_release_blocks_non_live_critical_stage():
    stages=['provider_ingest','candidate_promotion','blender','qa','export']
    evidence=[_ev(x) for x in stages]
    evidence[2]=_ev('blender',ExecutionMode.SYNTHETIC,True)
    r=evaluate_canonical_release(evidence,production_gate_passed=True)
    assert not r.releasable and 'blender' in r.non_live_stages


def test_canonical_release_passes_all_live_successful_stages():
    stages=['provider_ingest','candidate_promotion','blender','qa','export']
    r=evaluate_canonical_release([_ev(x) for x in stages],production_gate_passed=True)
    assert r.releasable and r.blockers==[] and len(r.live_stages)==5


def test_canonical_manifest_is_deterministic_at_fixed_time():
    artifacts=[CanonicalArtifact(name='character.glb',kind='model',size_bytes=10,sha256='a'*64)]
    evidence=[_ev(x) for x in ['provider_ingest','candidate_promotion','blender','qa','export']]
    a=compile_canonical_release_manifest('job',artifacts,evidence,production_gate_passed=True,created_at_unix=123)
    b=compile_canonical_release_manifest('job',artifacts,evidence,production_gate_passed=True,created_at_unix=123)
    assert a.manifest_sha256==b.manifest_sha256 and verify_canonical_manifest(a) and a.releasable


def test_artifact_from_path_hashes_real_bytes(tmp_path: Path):
    p=tmp_path/'asset.bin'; p.write_bytes(b'abc')
    a=artifact_from_path(p,kind='model')
    assert a.size_bytes==3 and a.sha256=='ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'


def test_blender_execution_receipt_requires_worker_success(tmp_path: Path):
    manifest=tmp_path/'manifest.json'; manifest.write_text('{}')
    worker=tmp_path/'worker.json'; worker.write_text(json.dumps({'status':'succeeded'}))
    inv=BlenderInvocation(executable='/fake/blender',args=['--background'])

    def runner(*args,**kwargs):
        return subprocess.CompletedProcess(args=args[0],returncode=0,stdout='ok',stderr='')

    r=execute_blender_with_receipt(inv,manifest_path=manifest,worker_receipt_path=worker,runner=runner)
    assert r.success and r.returncode==0 and r.worker_status=='succeeded' and r.manifest_sha256
    worker.unlink()
    r2=execute_blender_with_receipt(inv,manifest_path=manifest,worker_receipt_path=worker,runner=runner)
    assert not r2.success and r2.worker_status=='missing_receipt'


def test_runtime_readiness_never_exposes_secret(monkeypatch):
    monkeypatch.setenv('TRIPO_API_KEY','super-secret-value')
    monkeypatch.delenv('MESHY_API_KEY',raising=False)
    monkeypatch.delenv('HI3D_API_KEY',raising=False)
    r=detect_runtime_readiness(blender_executable='/definitely/not/a/blender')
    payload=r.model_dump_json()
    assert 'super-secret-value' not in payload
    tripo=[x for x in r.providers if x.name=='provider:tripo'][0]
    assert tripo.available

from app.release.canonical import write_canonical_manifest
from app.release.signed_manifest import sign_canonical_manifest, verify_signed_canonical_manifest
from app.security.release_signing import generate_ed25519_keypair


def test_signed_canonical_manifest_requires_releasable_manifest(tmp_path: Path):
    priv,_=generate_ed25519_keypair()
    artifacts=[CanonicalArtifact(name='x.glb',kind='model',size_bytes=1,sha256='a'*64)]
    bad=compile_canonical_release_manifest('job',artifacts,[_ev('provider_ingest',ExecutionMode.SYNTHETIC)],production_gate_passed=True,created_at_unix=1)
    p=write_canonical_manifest(bad,tmp_path/'bad.json')
    try:
        sign_canonical_manifest(p,priv,signed_at=2)
        assert False
    except ValueError as e:
        assert 'not releasable' in str(e)


def test_signed_canonical_manifest_verifies_and_detects_tamper(tmp_path: Path):
    priv,_=generate_ed25519_keypair()
    artifacts=[CanonicalArtifact(name='x.glb',kind='model',size_bytes=1,sha256='a'*64)]
    evidence=[_ev(x) for x in ['provider_ingest','candidate_promotion','blender','qa','export']]
    manifest=compile_canonical_release_manifest('job',artifacts,evidence,production_gate_passed=True,created_at_unix=1)
    p=write_canonical_manifest(manifest,tmp_path/'manifest.json')
    envelope=sign_canonical_manifest(p,priv,signed_at=2)
    assert verify_signed_canonical_manifest(p,envelope)
    p.write_text(p.read_text().replace('"job"','"tampered"',1))
    assert not verify_signed_canonical_manifest(p,envelope)
