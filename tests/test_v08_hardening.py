from pathlib import Path
import numpy as np
import trimesh

from app.qa.exact_intersections import triangles_intersect, detect_exact_self_intersections, compile_exact_intersection_repair_plan
from app.qa.identity_regions import IdentityRegion, compare_landmarks_by_region
from app.qa.rig import VertexWeights,RigWeightQAInput,qa_skin_weights,PoseDeformationSample,qa_pose_deformation
from app.rigging.correctives import CorrectiveNeed,compile_corrective_plan
from app.qa.groom_collision import qa_groom_collisions
from app.exports.usdskel import validate_usdskel
from app.runtime.leases import LeaseStore
from app.security.release_signing import generate_ed25519_keypair,sign_release,verify_release
from app.workers.bake_contract import compile_high_low_bake_contract


def test_triangle_triangle_exact_crossing_and_disjoint():
    a=np.array([[0,0,0],[1,0,0],[0,1,0]],float)
    b=np.array([[.25,.25,-1],[.25,.25,1],[.75,.25,0]],float)
    c=np.array([[2,2,1],[3,2,1],[2,3,1]],float)
    assert triangles_intersect(a,b)[0]
    assert not triangles_intersect(a,c)[0]


def test_exact_mesh_self_intersection(tmp_path: Path):
    verts=np.array([[0,0,0],[1,0,0],[0,1,0],[.25,.25,-1],[.25,.25,1],[.75,.25,0]],float)
    mesh=trimesh.Trimesh(vertices=verts,faces=[[0,1,2],[3,4,5]],process=False)
    p=tmp_path/'x.ply'; mesh.export(p)
    r=detect_exact_self_intersections(p)
    assert r.intersecting_pair_count==1
    plan=compile_exact_intersection_repair_plan(r)
    assert plan.strategy=='localized_patch_remesh' and plan.requires_external_kernel


def test_region_weighted_identity_focuses_eyes():
    ref=np.array([[0,0],[1,0],[0,1],[1,1],[.5,.5]],float); cand=ref.copy(); cand[0]+=[.3,0]
    regs=[IdentityRegion(name='eyes',indices=[0,1],weight=3),IdentityRegion(name='mouth',indices=[2,3,4],weight=1)]
    r=compare_landmarks_by_region(ref,cand,regs)
    assert len(r.regions)==2 and r.weighted_similarity<1
    assert any(x.name=='eyes' and x.weight==3 for x in r.regions)


def test_rig_weights_and_deformation_failures():
    good=qa_skin_weights(RigWeightQAInput(vertices=[VertexWeights(influences={'hip':.5,'spine':.5})],known_bones={'hip','spine'}))
    bad=qa_skin_weights(RigWeightQAInput(vertices=[VertexWeights(influences={'ghost':1.2})],known_bones={'hip'}))
    assert good.passed and not bad.passed
    poses=qa_pose_deformation([PoseDeformationSample(pose_name='elbow90',mean_edge_stretch=1.1,max_edge_stretch=1.5,relative_volume=.7,penetration_count=2)])
    assert not poses.passed and poses.failed_poses==['elbow90']


def test_corrective_morph_plan_prioritizes_penetration():
    p=compile_corrective_plan([CorrectiveNeed(pose_name='elbow90',joint='elbow.L',angle_degrees=90,max_edge_stretch=1.5,relative_volume=.7,penetration_count=2,identity_region='hand')])
    assert len(p.targets)==1 and p.targets[0].priority>=7 and p.driver=='pose_space_rbf'


def test_groom_collision_detects_inside_points(tmp_path: Path):
    body=trimesh.creation.box(extents=[2,2,2]); p=tmp_path/'body.ply'; body.export(p)
    strands=[[[0,0,1.05],[0,0,.5],[0,0,0]]]
    r=qa_groom_collisions(p,strands,sample_stride=1,allowed_penetration_ratio=0)
    assert r.penetration_point_count>=1 and not r.passed


def test_usdskel_static_validator(tmp_path: Path):
    p=tmp_path/'rig.usda'; p.write_text('#usda 1.0\ndef SkelRoot "Character" (\n prepend apiSchemas = ["SkelBindingAPI"]\n) {\n def Skeleton "Skeleton" {}\n rel skel:skeleton = </Character/Skeleton>\n}\n')
    r=validate_usdskel(p)
    assert r.parsed and r.passed and r.skeleton_count==1


def test_gpu_lease_heartbeat_and_reclaim(tmp_path: Path):
    store=LeaseStore(tmp_path/'leases.db'); a=store.acquire('gpu0','jobA',ttl_seconds=10,now=100)
    try:
        store.acquire('gpu0','jobB',ttl_seconds=10,now=101); assert False
    except RuntimeError: pass
    b=store.heartbeat('gpu0',a.token,ttl_seconds=10,now=105); assert b.expires_at==115
    assert store.reclaim_expired(now=116)==1
    c=store.acquire('gpu0','jobB',ttl_seconds=10,now=116); assert c.owner_id=='jobB'


def test_ed25519_release_signing_detects_tamper(tmp_path: Path):
    p=tmp_path/'release.zip'; p.write_bytes(b'release-bytes')
    priv,_=generate_ed25519_keypair(); env=sign_release(p,priv,key_id='ci')
    assert verify_release(p,env)
    p.write_bytes(b'tampered'); assert not verify_release(p,env)


def test_high_low_bake_contract_extreme_requires_cage():
    a=compile_high_low_bake_contract('hi.glb','lo.glb',extreme=True)
    assert a.blockers and any(c.name=='displacement' and c.bit_depth==32 for c in a.channels)
    b=compile_high_low_bake_contract('hi.glb','lo.glb',cage_mesh='cage.glb',extreme=True)
    assert not b.blockers and b.resolution==8192
