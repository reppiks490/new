from pathlib import Path

import numpy as np
import trimesh

from app.exports.usdskel import validate_usdskel
from app.pipeline.production_chain import ProductionStage, compile_production_chain_plan, run_production_chain
from app.qa.exact_intersections import ExactIntersectionReport
from app.qa.groom_animation import GroomFrameSample, qa_animated_groom_collisions
from app.qa.identity_regions import IdentityRegion, compare_landmarks_by_region
from app.qa.mesh import inspect_mesh
from app.qa.repair_acceptance import evaluate_repair_acceptance
from app.runtime.claims import JobClaimStore
from app.workers.bake_adapters import compile_bake_adapters
from app.workers.bake_contract import compile_high_low_bake_contract
from app.workers.localized_repair import compile_localized_repair_contract, build_localized_repair_invocation


def _report(path: str, pairs: int) -> ExactIntersectionReport:
    return ExactIntersectionReport(
        path=path, face_count=10, tested_pairs=5, intersecting_pair_count=pairs,
        intersecting_face_count=pairs * 2, intersecting_ratio=min(1, pairs * 0.2), pairs=[],
    )


def test_repair_acceptance_requires_identity_and_intersection_improvement(tmp_path: Path):
    box = trimesh.creation.box(); before = tmp_path/'before.ply'; after = tmp_path/'after.ply'; box.export(before); box.export(after)
    mesh_before = inspect_mesh(before); mesh_after = inspect_mesh(after)
    ref=np.array([[0,0],[1,0],[0,1],[1,1]],float); cand=ref.copy()
    identity=compare_landmarks_by_region(ref,cand,[IdentityRegion(name='face',indices=[0,1,2,3],weight=3)])
    ok=evaluate_repair_acceptance(_report(str(before),2),_report(str(after),0),mesh_before,mesh_after,identity)
    assert ok.accepted and ok.intersection_reduction==2
    bad=evaluate_repair_acceptance(_report(str(before),2),_report(str(after),2),mesh_before,mesh_after,identity)
    assert not bad.accepted


def test_localized_repair_contract_refuses_truncated_report():
    r=ExactIntersectionReport(path='x',face_count=100,tested_pairs=100,intersecting_pair_count=1,intersecting_face_count=2,intersecting_ratio=.02,pairs=[],truncated=True)
    c=compile_localized_repair_contract(r,'source.glb','out.glb')
    assert c.blockers
    inv=build_localized_repair_invocation('/opt/blender','contract.json','repair.py')
    assert '--disable-autoexec' in inv.command and '--contract' in inv.command


def test_retry_safe_job_claiming(tmp_path: Path):
    s=JobClaimStore(tmp_path/'claims.db'); s.enqueue('j1',available_at=100)
    a=s.claim('j1','workerA',ttl_seconds=10,now=100); assert a.attempt==1
    r=s.fail('j1',a.token,retryable=True,error='transient',retry_delay=5,now=101); assert r.state=='retry_wait'
    try:
        s.claim('j1','workerB',now=104); assert False
    except RuntimeError: pass
    b=s.claim('j1','workerB',now=106); assert b.attempt==2
    done=s.complete('j1',b.token,now=107); assert done.state=='succeeded'


def test_animated_groom_aggregates_failed_frames(tmp_path: Path):
    body=trimesh.creation.box(extents=[2,2,2]); p=tmp_path/'body.ply'; body.export(p)
    samples=[
        GroomFrameSample(frame=1,strands=[[[0,0,1.2],[0,0,1.1]]]),
        GroomFrameSample(frame=2,strands=[[[0,0,1.05],[0,0,.5]]]),
    ]
    r=qa_animated_groom_collisions(p,samples,sample_stride=1,allowed_penetration_ratio=0)
    assert r.frame_count==2 and 2 in r.failed_frames and not r.passed


def test_usdskel_static_checks_joint_arrays(tmp_path: Path):
    p=tmp_path/'rig.usda'
    p.write_text('''#usda 1.0\ndef SkelRoot "Character" (\n prepend apiSchemas = ["SkelBindingAPI"]\n) {\n def Skeleton "Skeleton" {\n  uniform token[] joints = ["root", "root/spine"]\n  uniform matrix4d[] bindTransforms = [((1,0,0,0),(0,1,0,0),(0,0,1,0),(0,0,0,1)), ((1,0,0,0),(0,1,0,0),(0,0,1,0),(0,0,0,1))]\n  uniform matrix4d[] restTransforms = [((1,0,0,0),(0,1,0,0),(0,0,1,0),(0,0,0,1)), ((1,0,0,0),(0,1,0,0),(0,0,1,0),(0,0,0,1))]\n }\n rel skel:skeleton = </Character/Skeleton>\n int[] primvars:skel:jointIndices = [0,1]\n}\n''')
    r=validate_usdskel(p)
    assert r.parsed and r.skeletons_with_joints==1 and r.influence_prim_count>=1 and r.passed and r.production_ready


def test_bake_adapter_plan_requires_explicit_source_bindings():
    c=compile_high_low_bake_contract('hi.glb','lo.glb',cage_mesh='cage.glb',extreme=True)
    p=compile_bake_adapters(c)
    by={x.channel:x for x in p.adapters}
    assert by['normal'].executable and not by['displacement'].executable and not by['curvature'].executable and not by['thickness'].executable
    p2=compile_bake_adapters(c,displacement_binding='height',curvature_attribute='curv',thickness_attribute='thick')
    assert all(x.executable for x in p2.adapters)


def test_production_chain_is_hash_linked_and_stops_on_gate_failure():
    plan=compile_production_chain_plan('job1','tripo',authenticated=True,require_repair=False,require_bake=False)
    handlers={s:(lambda s=s:{'status':'succeeded','stage':s.value}) for s in plan.stages}
    report=run_production_chain(plan,handlers)
    assert report.status=='succeeded' and len(report.receipts)==len(plan.stages)
    for i in range(1,len(report.receipts)):
        assert report.receipts[i].previous_sha256==report.receipts[i-1].payload_sha256
    bad=handlers.copy(); bad[ProductionStage.QA]=lambda:{'passed':False,'error':'identity drift'}
    failed=run_production_chain(plan,bad)
    assert failed.status=='failed' and ProductionStage.EXPORT not in failed.completed_stages
