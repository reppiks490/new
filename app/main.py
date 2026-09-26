from pathlib import Path
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator
from app.core.models import CharacterSpec, HardwareProfile
from app.core.policy import evaluate_policy
from app.pipeline.planner import compile_plan
from app.runtime.compile_job import compile_job_manifest
from app.runtime.hardware import detect_runtime_hardware
from app.packs.manager import PackRegistry
from app.providers.catalog import gap_fill_capabilities, provider_profiles
from app.providers.router import RouteContext, compile_provider_routing
from app.render.output_resolution import RenderResolutionTier

app = FastAPI(title="Character3D Masterbuild", version="1.3.0")
PACK_REGISTRY_PATH = Path(__file__).parents[1] / "config" / "packs" / "registry.yaml"


class PlanRequest(BaseModel):
    character: CharacterSpec
    hardware: HardwareProfile = Field(default_factory=HardwareProfile)
    reference_image_path: str | None = None
    render_quality_mode: str = "hero"
    render_resolution_tier: RenderResolutionTier = RenderResolutionTier.UHD_8K


class JobRequest(PlanRequest):
    workspace: str = "./workspace"


class PackRequest(BaseModel):
    pack_ids: list[str]


@app.get("/health")
def health():
    return {"ok": True, "version": "1.3.0"}


@app.get("/v1/hardware")
def hardware():
    return detect_runtime_hardware()


@app.post("/v1/validate")
def validate(spec: CharacterSpec):
    return evaluate_policy(spec)


@app.post("/v1/plan")
def plan(req: PlanRequest):
    try:
        return compile_plan(
            req.character, req.hardware,
            reference_image_path=req.reference_image_path,
            render_quality_mode=req.render_quality_mode,
            render_resolution_tier=req.render_resolution_tier,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.post("/v1/jobs/compile")
def compile_job(req: JobRequest):
    manifest = compile_job_manifest(req.character, req.hardware, req.workspace)
    if not compile_plan(req.character, req.hardware).policy.allowed:
        raise HTTPException(status_code=422, detail="Request is blocked by policy gate")
    return manifest


class ProviderRouteRequest(BaseModel):
    character: CharacterSpec
    source_kind: str = "prompt"
    prioritize_portrait_fidelity: bool = True
    prioritize_printability: bool = False
    require_rigging: bool = True
    require_segmentation: bool = True


@app.get("/v1/providers")
def providers():
    return {"providers": [p.model_dump(mode="json") for p in provider_profiles()]}


@app.get("/v1/providers/gap-fill")
def provider_gap_fill():
    return {"relative_to": "tripo", "gap_fill": gap_fill_capabilities()}


@app.post("/v1/providers/route")
def route_providers(req: ProviderRouteRequest):
    ctx = RouteContext(
        source_kind=req.source_kind,
        prioritize_portrait_fidelity=req.prioritize_portrait_fidelity,
        prioritize_printability=req.prioritize_printability,
        require_rigging=req.require_rigging,
        require_segmentation=req.require_segmentation,
    )
    return compile_provider_routing(req.character, ctx)


@app.get("/v1/packs")
def packs():
    reg = PackRegistry.from_yaml(PACK_REGISTRY_PATH)
    return {"packs": [p.model_dump() for p in reg.packs.values()]}


@app.post("/v1/packs/resolve")
def resolve_packs(req: PackRequest):
    reg = PackRegistry.from_yaml(PACK_REGISTRY_PATH)
    try:
        resolved = reg.resolve(req.pack_ids)
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "packs": [p.model_dump() for p in resolved],
        "expected_size_gb": reg.expected_size_gb(req.pack_ids),
    }

from app.materials.udim import plan_character_udims
from app.render.cycles import maximum_quality_preset


class UDIMRequest(BaseModel):
    tiles: int = 8
    resolution: int = 8192


@app.post("/v1/materials/udim-plan")
def udim_plan(req: UDIMRequest):
    try:
        return plan_character_udims(req.tiles, resolution=req.resolution)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class CyclesPresetRequest(BaseModel):
    vram_gb: float = 24
    gpu_vendor: str = "nvidia"


@app.post("/v1/render/cycles-preset")
def cycles_preset(req: CyclesPresetRequest):
    try:
        return maximum_quality_preset(req.vram_gb, gpu_vendor=req.gpu_vendor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


from app.qa.repair import compile_repair_plan
from app.qa.identity import compare_landmarks
from app.qa.specialized import SkinQAInput, EyeQAInput, GroomQAInput, qa_skin, qa_eyes, qa_groom
from app.exports.validation import validate_export
from app.runtime.gpu_scheduler import GPUJobRequest, GPUWorker, choose_gpu_worker
from app.workers.blender_pipeline import compile_blender_production_manifest


class RepairPlanRequest(BaseModel):
    path: str


@app.post("/v1/qa/repair-plan")
def repair_plan(req: RepairPlanRequest):
    try:
        return compile_repair_plan(req.path)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class IdentityRequest(BaseModel):
    reference: list[list[float]]
    candidate: list[list[float]]


@app.post("/v1/qa/identity")
def identity(req: IdentityRequest):
    try:
        return compare_landmarks(req.reference, req.candidate)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/v1/qa/skin")
def skin_qa(req: SkinQAInput):
    return qa_skin(req)


@app.post("/v1/qa/eyes")
def eye_qa(req: EyeQAInput):
    return qa_eyes(req)


@app.post("/v1/qa/groom")
def groom_qa(req: GroomQAInput):
    return qa_groom(req)


class ExportValidationRequest(BaseModel):
    path: str


@app.post("/v1/exports/validate")
def export_validate(req: ExportValidationRequest):
    try:
        return validate_export(req.path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


class ScheduleGPURequest(BaseModel):
    workers: list[GPUWorker]
    job: GPUJobRequest


@app.post("/v1/runtime/schedule-gpu")
def schedule_gpu(req: ScheduleGPURequest):
    try:
        return choose_gpu_worker(req.workers, req.job)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


class BlenderManifestRequest(BaseModel):
    source_model: str
    workspace: str
    vram_gb: float = 24
    gpu_vendor: str = "nvidia"
    render_mode: str = "hero"
    udim_tiles: list[int] = Field(default_factory=lambda: list(range(1001, 1009)))
    resolution: int = 8192
    export_formats: list[str] = Field(default_factory=lambda: ["glb", "usd"])


@app.post("/v1/blender/production-manifest")
def blender_production_manifest(req: BlenderManifestRequest):
    try:
        return compile_blender_production_manifest(
            req.source_model, req.workspace, vram_gb=req.vram_gb, gpu_vendor=req.gpu_vendor,
            render_mode=req.render_mode, udim_tiles=req.udim_tiles, resolution=req.resolution,
            export_formats=req.export_formats,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

# v0.8 hardening surfaces
from app.qa.exact_intersections import detect_exact_self_intersections, compile_exact_intersection_repair_plan
from app.qa.identity_regions import IdentityRegion, compare_landmarks_by_region
from app.qa.rig import RigWeightQAInput, PoseDeformationSample, qa_skin_weights, qa_pose_deformation
from app.qa.groom_collision import qa_groom_collisions
from app.exports.usdskel import validate_usdskel
from app.rigging.correctives import CorrectiveNeed, compile_corrective_plan
from app.workers.bake_contract import compile_high_low_bake_contract


class ExactIntersectionRequest(BaseModel):
    path: str
    max_pairs: int = 2000


@app.post('/v1/qa/exact-intersections')
def exact_intersections(req: ExactIntersectionRequest):
    try:
        report = detect_exact_self_intersections(req.path, max_pairs=req.max_pairs)
        return {'report': report, 'repair_plan': compile_exact_intersection_repair_plan(report)}
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class WeightedIdentityRequest(BaseModel):
    reference: list[list[float]]
    candidate: list[list[float]]
    regions: list[IdentityRegion]


@app.post('/v1/qa/identity-regions')
def identity_regions(req: WeightedIdentityRequest):
    try:
        return compare_landmarks_by_region(req.reference, req.candidate, req.regions)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post('/v1/qa/rig-weights')
def rig_weights(req: RigWeightQAInput):
    return qa_skin_weights(req)


class PoseDeformationRequest(BaseModel):
    samples: list[PoseDeformationSample]
    max_stretch: float = 1.35
    min_volume: float = 0.80
    max_volume: float = 1.20


@app.post('/v1/qa/pose-deformation')
def pose_deformation(req: PoseDeformationRequest):
    return qa_pose_deformation(req.samples, max_stretch=req.max_stretch, min_volume=req.min_volume, max_volume=req.max_volume)


class CorrectivePlanRequest(BaseModel):
    needs: list[CorrectiveNeed]


@app.post('/v1/rigging/correctives/plan')
def corrective_plan(req: CorrectivePlanRequest):
    return compile_corrective_plan(req.needs)


class GroomCollisionRequest(BaseModel):
    body_mesh: str
    strands: list[list[list[float]]]
    sample_stride: int = 2
    allowed_penetration_ratio: float = 0.002


@app.post('/v1/qa/groom-collisions')
def groom_collisions(req: GroomCollisionRequest):
    try:
        return qa_groom_collisions(req.body_mesh, req.strands, sample_stride=req.sample_stride, allowed_penetration_ratio=req.allowed_penetration_ratio)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class UsdSkelRequest(BaseModel):
    path: str


@app.post('/v1/exports/validate-usdskel')
def usdskel_validate(req: UsdSkelRequest):
    try:
        return validate_usdskel(req.path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


class BakeContractRequest(BaseModel):
    high_mesh: str
    low_mesh: str
    cage_mesh: str | None = None
    udim_tiles: list[int] = Field(default_factory=lambda: list(range(1001,1009)))
    resolution: int = 8192
    extreme: bool = False


@app.post('/v1/blender/high-low-bake-contract')
def high_low_bake_contract(req: BakeContractRequest):
    return compile_high_low_bake_contract(req.high_mesh, req.low_mesh, cage_mesh=req.cage_mesh, udim_tiles=req.udim_tiles, resolution=req.resolution, extreme=req.extreme)

from app.runtime.leases import LeaseStore
from app.qa.production_gate import GateCheck, compile_production_gate


class LeaseAcquireRequest(BaseModel):
    worker_id: str
    owner_id: str
    ttl_seconds: float = 30


class LeaseHeartbeatRequest(BaseModel):
    worker_id: str
    token: str
    ttl_seconds: float = 30


class LeaseReleaseRequest(BaseModel):
    worker_id: str
    token: str


def _lease_store() -> LeaseStore:
    # Server-controlled path: API callers never choose an arbitrary local filesystem target.
    db_path = os.environ.get("CHARACTER3D_LEASE_DB", "./workspace/runtime_leases.db")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return LeaseStore(db_path)


@app.post('/v1/runtime/leases/acquire')
def lease_acquire(req: LeaseAcquireRequest):
    try:
        return _lease_store().acquire(req.worker_id, req.owner_id, ttl_seconds=req.ttl_seconds)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@app.post('/v1/runtime/leases/heartbeat')
def lease_heartbeat(req: LeaseHeartbeatRequest):
    try:
        return _lease_store().heartbeat(req.worker_id, req.token, ttl_seconds=req.ttl_seconds)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@app.post('/v1/runtime/leases/release')
def lease_release(req: LeaseReleaseRequest):
    return {'released': _lease_store().release(req.worker_id, req.token)}


@app.post('/v1/runtime/leases/reclaim-expired')
def lease_reclaim():
    return {'reclaimed': _lease_store().reclaim_expired()}


class ProductionGateRequest(BaseModel):
    checks: list[GateCheck]


@app.post('/v1/qa/production-gate')
def production_gate(req: ProductionGateRequest):
    return compile_production_gate(req.checks)


# v0.9 execution-chain surfaces
from app.qa.repair_acceptance import RepairAcceptancePolicy, evaluate_repair_acceptance
from app.qa.groom_animation import GroomFrameSample, qa_animated_groom_collisions
from app.qa.mesh import inspect_mesh
from app.runtime.claims import JobClaimStore
from app.workers.localized_repair import compile_localized_repair_contract
from app.workers.bake_adapters import compile_bake_adapters
from app.pipeline.production_chain import compile_production_chain_plan
from app.providers.auth import auth_status


class RepairAcceptanceRequest(BaseModel):
    before_mesh: str
    after_mesh: str
    before_intersections: dict
    after_intersections: dict
    identity_reference: list[list[float]]
    identity_candidate: list[list[float]]
    regions: list[IdentityRegion]
    policy: RepairAcceptancePolicy = Field(default_factory=RepairAcceptancePolicy)


@app.post('/v1/qa/repair-acceptance')
def repair_acceptance(req: RepairAcceptanceRequest):
    from app.qa.exact_intersections import ExactIntersectionReport
    try:
        before_i = ExactIntersectionReport.model_validate(req.before_intersections)
        after_i = ExactIntersectionReport.model_validate(req.after_intersections)
        before_m = inspect_mesh(req.before_mesh)
        after_m = inspect_mesh(req.after_mesh)
        identity = compare_landmarks_by_region(req.identity_reference, req.identity_candidate, req.regions)
        return evaluate_repair_acceptance(before_i, after_i, before_m, after_m, identity, req.policy)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class AnimatedGroomRequest(BaseModel):
    body_mesh: str
    samples: list[GroomFrameSample]
    sample_stride: int = 2
    allowed_penetration_ratio: float = 0.002


@app.post('/v1/qa/groom-collisions/animated')
def animated_groom(req: AnimatedGroomRequest):
    try:
        return qa_animated_groom_collisions(req.body_mesh, req.samples, sample_stride=req.sample_stride, allowed_penetration_ratio=req.allowed_penetration_ratio)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class LocalizedRepairRequest(BaseModel):
    report: dict
    source_mesh: str
    output_mesh: str


@app.post('/v1/blender/localized-repair-contract')
def localized_repair_contract(req: LocalizedRepairRequest):
    from app.qa.exact_intersections import ExactIntersectionReport
    try:
        report = ExactIntersectionReport.model_validate(req.report)
        return compile_localized_repair_contract(report, req.source_mesh, req.output_mesh)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class BakeAdapterRequest(BaseModel):
    high_mesh: str
    low_mesh: str
    cage_mesh: str | None = None
    extreme: bool = False
    displacement_binding: str | None = None
    curvature_attribute: str | None = None
    thickness_attribute: str | None = None


@app.post('/v1/blender/bake-adapters')
def bake_adapters(req: BakeAdapterRequest):
    contract = compile_high_low_bake_contract(req.high_mesh, req.low_mesh, cage_mesh=req.cage_mesh, extreme=req.extreme)
    return compile_bake_adapters(contract, displacement_binding=req.displacement_binding, curvature_attribute=req.curvature_attribute, thickness_attribute=req.thickness_attribute)


def _claim_store() -> JobClaimStore:
    db_path = os.environ.get('CHARACTER3D_CLAIM_DB', './workspace/job_claims.db')
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return JobClaimStore(db_path)


class JobEnqueueRequest(BaseModel):
    job_id: str


class JobClaimRequest(BaseModel):
    job_id: str
    owner_id: str
    ttl_seconds: float = 60


class JobClaimHeartbeatRequest(BaseModel):
    job_id: str
    token: str
    ttl_seconds: float = 60


class JobClaimCompleteRequest(BaseModel):
    job_id: str
    token: str


class JobClaimFailRequest(BaseModel):
    job_id: str
    token: str
    retryable: bool = True
    error: str
    retry_delay: float = 30


@app.post('/v1/runtime/jobs/enqueue')
def job_enqueue(req: JobEnqueueRequest):
    return _claim_store().enqueue(req.job_id)


@app.post('/v1/runtime/jobs/claim')
def job_claim(req: JobClaimRequest):
    try:
        return _claim_store().claim(req.job_id, req.owner_id, ttl_seconds=req.ttl_seconds)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@app.post('/v1/runtime/jobs/heartbeat')
def job_claim_heartbeat(req: JobClaimHeartbeatRequest):
    try:
        return _claim_store().heartbeat(req.job_id, req.token, ttl_seconds=req.ttl_seconds)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@app.post('/v1/runtime/jobs/complete')
def job_claim_complete(req: JobClaimCompleteRequest):
    try:
        return _claim_store().complete(req.job_id, req.token)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@app.post('/v1/runtime/jobs/fail')
def job_claim_fail(req: JobClaimFailRequest):
    try:
        return _claim_store().fail(req.job_id, req.token, retryable=req.retryable, error=req.error, retry_delay=req.retry_delay)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


class ProductionChainPlanRequest(BaseModel):
    job_id: str
    provider: str
    require_repair: bool = True
    require_bake: bool = True


@app.get('/v1/providers/{provider}/auth-status')
def provider_auth_status(provider: str):
    try:
        return auth_status(provider)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.post('/v1/pipeline/production-chain-plan')
def production_chain_plan(req: ProductionChainPlanRequest):
    try:
        status = auth_status(req.provider)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return compile_production_chain_plan(req.job_id, req.provider, authenticated=status.configured, require_repair=req.require_repair, require_bake=req.require_bake)

# v1.0 execution-truth and canonical-release surfaces
from app.runtime.capabilities import detect_runtime_readiness
from app.release.canonical import (
    CanonicalArtifact,
    compile_canonical_release_manifest,
    evaluate_canonical_release,
)
from app.workers.execution_evidence import ExecutionEvidence


@app.get('/v1/runtime/readiness')
def runtime_readiness():
    return detect_runtime_readiness()


class CanonicalReleaseEvaluateRequest(BaseModel):
    evidence: list[ExecutionEvidence]
    production_gate_passed: bool
    required_live_stages: list[str] | None = None


@app.post('/v1/release/evaluate')
def canonical_release_evaluate(req: CanonicalReleaseEvaluateRequest):
    return evaluate_canonical_release(
        req.evidence,
        production_gate_passed=req.production_gate_passed,
        required_live_stages=req.required_live_stages,
    )


class CanonicalReleaseManifestRequest(BaseModel):
    job_id: str
    artifacts: list[CanonicalArtifact]
    evidence: list[ExecutionEvidence]
    production_gate_passed: bool
    required_live_stages: list[str] | None = None
    created_at_unix: int | None = None


@app.post('/v1/release/canonical-manifest')
def canonical_release_manifest(req: CanonicalReleaseManifestRequest):
    return compile_canonical_release_manifest(
        req.job_id,
        req.artifacts,
        req.evidence,
        production_gate_passed=req.production_gate_passed,
        required_live_stages=req.required_live_stages,
        created_at_unix=req.created_at_unix,
    )


# v1.2 reproducibility, lineage, rollback, and export-integrity surfaces
from app.exports.gltf_validation import validate_gltf_structure
from app.release.canonical import CanonicalReleaseManifest
from app.release.diff import compare_canonical_releases
from app.release.reproducibility import compile_build_fingerprint, capture_runtime_environment
from app.runtime.checkpoints import StageCheckpoint, StageCheckpointStore
from app.runtime.lineage import ArtifactLineageStore


def _source_root() -> Path:
    return Path(os.environ.get("CHARACTER3D_SOURCE_ROOT", str(Path(__file__).parents[1]))).resolve()


def _lineage_store() -> ArtifactLineageStore:
    db_path = os.environ.get("CHARACTER3D_LINEAGE_DB", "./workspace/artifact_lineage.db")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return ArtifactLineageStore(db_path)


def _checkpoint_store() -> StageCheckpointStore:
    db_path = os.environ.get("CHARACTER3D_CHECKPOINT_DB", "./workspace/stage_checkpoints.db")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return StageCheckpointStore(db_path)


@app.get('/v1/release/build-fingerprint')
def build_fingerprint():
    root = _source_root()
    return {
        'root': str(root),
        'fingerprint': compile_build_fingerprint(root, metadata={'project': 'character3d-masterbuild', 'version': '1.3.0'}),
        'environment': capture_runtime_environment(),
    }


class GltfValidationRequest(BaseModel):
    path: str


@app.post('/v1/exports/validate-gltf')
def export_validate_gltf(req: GltfValidationRequest):
    try:
        return validate_gltf_structure(req.path)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class LineageRegisterRequest(BaseModel):
    asset_id: str
    sha256: str
    stage: str
    parent_sha256: str | None = None
    path: str | None = None
    branch: str = 'main'
    metadata: dict = Field(default_factory=dict)
    activate: bool = True


@app.post('/v1/runtime/lineage/register')
def lineage_register(req: LineageRegisterRequest):
    try:
        return _lineage_store().register(
            req.asset_id, req.sha256, req.stage, parent_sha256=req.parent_sha256, path=req.path,
            branch=req.branch, metadata=req.metadata, activate=req.activate,
        )
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get('/v1/runtime/lineage/{asset_id}')
def lineage_history(asset_id: str):
    store = _lineage_store()
    return {'asset_id': asset_id, 'current': store.current(asset_id), 'history': store.history(asset_id)}


class LineageRollbackRequest(BaseModel):
    asset_id: str
    target_sha256: str
    reason: str
    expected_current_sha256: str | None = None


@app.post('/v1/runtime/lineage/rollback')
def lineage_rollback(req: LineageRollbackRequest):
    try:
        return _lineage_store().rollback(
            req.asset_id, req.target_sha256, reason=req.reason, expected_current_sha256=req.expected_current_sha256,
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@app.post('/v1/runtime/checkpoints/append')
def checkpoint_append(checkpoint: StageCheckpoint):
    try:
        return _checkpoint_store().append(checkpoint)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get('/v1/runtime/checkpoints/{job_id}')
def checkpoint_chain(job_id: str):
    store = _checkpoint_store()
    return {'job_id': job_id, 'valid_chain': store.verify_chain(job_id), 'checkpoints': store.chain(job_id)}


class CheckpointRollbackRequest(BaseModel):
    job_id: str
    target_checkpoint_sha256: str


@app.post('/v1/runtime/checkpoints/rollback-plan')
def checkpoint_rollback_plan(req: CheckpointRollbackRequest):
    try:
        return _checkpoint_store().rollback_plan(req.job_id, req.target_checkpoint_sha256)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


class CanonicalDiffRequest(BaseModel):
    before: CanonicalReleaseManifest
    after: CanonicalReleaseManifest


@app.post('/v1/release/diff')
def canonical_release_diff(req: CanonicalDiffRequest):
    return compare_canonical_releases(req.before, req.after)


# --- v1.3: scenes, worlds, rendering, topology --------------------------
# Session capability that previously had no HTTP surface at all -- see
# docs/V13_WORLDS_AND_RENDERING.md. Follows the same file-path request
# convention already used above (e.g. ExportValidationRequest).

from app.core.scene_models import SceneSpec
from app.pipeline.scene_planner import compile_scene_plan
from app.qa.scene import qa_scene_placement
from app.world.terrain import TerrainSpec, diamond_square_heightmap, generate_terrain_mesh, generate_terrain_mesh_with_biomes
from app.world.world_grid import WorldGridSpec, generate_master_heightmap, tile_mesh
from app.core.body_morphs import BodyMorphSpec
from app.rigging.body_morph_apply import apply_body_morphs, apply_body_morphs_auto
from app.render.job import compile_render_job
from app.render.output_resolution import RenderOutputSpec, render_output_spec_for_tier
from app.render.output_verification import verify_render_output
from app.qa.topology import analyze_obj_topology
from app.pipeline.image_analysis import analyze_image_for_prompt
from app.providers.hi3d_modes import multicolor_task_fields, portrait_task_fields, print_split_task_fields, relief_task_fields


class ScenePlanRequest(BaseModel):
    scene: SceneSpec
    hardware: HardwareProfile = Field(default_factory=HardwareProfile)


@app.post("/v1/scenes/plan")
def scene_plan(req: ScenePlanRequest):
    return compile_scene_plan(req.scene, req.hardware)


@app.post("/v1/scenes/placement-qa")
def scene_placement_qa(scene: SceneSpec):
    return qa_scene_placement(scene)


class TerrainGenerateRequest(BaseModel):
    terrain: TerrainSpec
    output_path: str
    with_biomes: bool = False


@app.post("/v1/world/terrain/generate")
def terrain_generate(req: TerrainGenerateRequest):
    mesh = generate_terrain_mesh_with_biomes(req.terrain) if req.with_biomes else generate_terrain_mesh(req.terrain)
    out = Path(req.output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(out)
    return {"output_path": str(out), "vertex_count": len(mesh.vertices), "face_count": len(mesh.faces), "with_biomes": req.with_biomes}


class TerrainBestOfNRequest(BaseModel):
    terrain: TerrainSpec
    candidate_seeds: list[int]
    output_path: str
    with_biomes: bool = True


@app.post("/v1/world/terrain/generate-best-of-n")
def terrain_generate_best_of_n(req: TerrainBestOfNRequest):
    from app.world.terrain_selection import select_best_terrain_seed

    try:
        result = select_best_terrain_seed(req.terrain, candidate_seeds=req.candidate_seeds)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    winning_spec = req.terrain.model_copy(update={"seed": result.best_seed})
    mesh = generate_terrain_mesh_with_biomes(winning_spec) if req.with_biomes else generate_terrain_mesh(winning_spec)
    out = Path(req.output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(out)
    return {
        "output_path": str(out),
        "vertex_count": len(mesh.vertices),
        "face_count": len(mesh.faces),
        "best_seed": result.best_seed,
        "best_score": {
            "biome_diversity": result.best_score.biome_diversity,
            "walkable_ratio": result.best_score.walkable_ratio,
            "height_utilization": result.best_score.height_utilization,
            "composite": result.best_score.composite,
        },
        "all_candidate_scores": [
            {
                "seed": s.seed,
                "biome_diversity": s.biome_diversity,
                "walkable_ratio": s.walkable_ratio,
                "height_utilization": s.height_utilization,
                "composite": s.composite,
            }
            for s in result.all_scores
        ],
    }


class BiomeTextureSynthesisRequest(BaseModel):
    terrain: TerrainSpec
    texture_size: int = Field(default=1024, gt=0, le=16384)
    basecolor_path: str
    roughness_path: str


@app.post("/v1/world/terrain/biome-texture")
def world_terrain_biome_texture(req: BiomeTextureSynthesisRequest):
    from app.world.biome_texture_synthesis import export_biome_texture_maps

    heightmap = diamond_square_heightmap(req.terrain)
    try:
        result = export_biome_texture_maps(
            heightmap,
            texture_size=req.texture_size,
            basecolor_path=req.basecolor_path,
            roughness_path=req.roughness_path,
            seed=req.terrain.seed,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return result


class WorldTileRequest(BaseModel):
    world: WorldGridSpec
    tile_x: int
    tile_z: int
    lod: int = 0
    with_biomes: bool = True
    output_path: str


@app.post("/v1/world/tile/generate")
def world_tile_generate(req: WorldTileRequest):
    try:
        master = generate_master_heightmap(req.world)
        mesh = tile_mesh(master, req.world, req.tile_x, req.tile_z, lod=req.lod, with_biomes=req.with_biomes)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    out = Path(req.output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(out)
    return {"output_path": str(out), "vertex_count": len(mesh.vertices), "face_count": len(mesh.faces)}


class BodyMorphApplyRequest(BaseModel):
    input_path: str
    output_path: str
    # Either morphs (raw -1..1 sliders) or percentages (-100..100, the
    # friendlier scale most mainstream character creators present) --
    # exactly one must be supplied.
    morphs: BodyMorphSpec | None = None
    percentages: dict[str, float] | None = None
    # Any region not present here is auto-estimated from the mesh's own
    # bounding box when auto_weights=True (the default) -- no manual setup
    # needed for the 11 supported regions (everything except arms/hands;
    # see app/rigging/auto_region_weights.py::UNSUPPORTED_REGIONS).
    region_weights: dict[str, list[float]] = {}
    auto_weights: bool = True

    @model_validator(mode="after")
    def validate_exactly_one_morph_input(self):
        if (self.morphs is None) == (self.percentages is None):
            raise ValueError("exactly one of morphs or percentages must be supplied")
        return self


@app.post("/v1/body-morphs/apply")
def body_morphs_apply(req: BodyMorphApplyRequest):
    import numpy as np
    import trimesh

    in_path = Path(req.input_path)
    if not in_path.is_file():
        raise HTTPException(status_code=404, detail=f"{in_path} does not exist")
    mesh = trimesh.load(in_path, force="mesh", process=False)
    weights = {name: np.asarray(values, dtype=np.float64) for name, values in req.region_weights.items()}
    morphs = req.morphs if req.morphs is not None else BodyMorphSpec.from_percentages(req.percentages)
    try:
        if req.auto_weights:
            out_mesh = apply_body_morphs_auto(mesh, morphs, weights)
        else:
            out_mesh = apply_body_morphs(mesh, morphs, weights)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    out = Path(req.output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out_mesh.export(out)
    return {"output_path": str(out), "vertex_count": len(out_mesh.vertices)}


class ThreeJSPreviewRequest(BaseModel):
    input_path: str
    background_hex: int = 0x1a1a2e
    material_color_hex: int = 0x8899aa
    wireframe: bool = False


@app.post("/v1/viz/threejs-scene")
def viz_threejs_scene(req: ThreeJSPreviewRequest):
    import trimesh

    from app.viz.threejs_export import mesh_to_threejs_code

    in_path = Path(req.input_path)
    if not in_path.is_file():
        raise HTTPException(status_code=404, detail=f"{in_path} does not exist")
    mesh = trimesh.load(in_path, force="mesh", process=False)
    try:
        code = mesh_to_threejs_code(
            mesh,
            background_hex=req.background_hex,
            material_color_hex=req.material_color_hex,
            wireframe=req.wireframe,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {"threejs_code": code, "vertex_count": len(mesh.vertices), "face_count": len(mesh.faces)}


class RenderJobRequest(BaseModel):
    vram_gb: float
    ram_gb: float
    gpu_vendor: str = "nvidia"
    quality_mode: str = "hero"
    resolution_tier: RenderResolutionTier = RenderResolutionTier.UHD_8K
    overscan_px: int = 0
    bit_depth: int = 16
    passes: list[str] | None = None


@app.post("/v1/render/job/compile")
def render_job_compile(req: RenderJobRequest):
    try:
        return compile_render_job(
            vram_gb=req.vram_gb, ram_gb=req.ram_gb, gpu_vendor=req.gpu_vendor,
            quality_mode=req.quality_mode, resolution_tier=req.resolution_tier,
            overscan_px=req.overscan_px, bit_depth=req.bit_depth, passes=req.passes,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


class RenderOutputVerifyRequest(BaseModel):
    resolution_tier: RenderResolutionTier
    output_path: str
    overscan_px: int = 0
    bit_depth: int = 16


@app.post("/v1/render/output/verify")
def render_output_verify(req: RenderOutputVerifyRequest):
    spec = render_output_spec_for_tier(req.resolution_tier, overscan_px=req.overscan_px, bit_depth=req.bit_depth)
    return verify_render_output(spec, req.output_path)


class TopologyRequest(BaseModel):
    path: str


@app.post("/v1/qa/topology")
def qa_topology(req: TopologyRequest):
    try:
        return analyze_obj_topology(req.path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


class ImageAnalysisRequest(BaseModel):
    path: str
    palette_size: int = 5


@app.post("/v1/pipeline/image-analysis")
def pipeline_image_analysis(req: ImageAnalysisRequest):
    try:
        return analyze_image_for_prompt(req.path, palette_size=req.palette_size)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


class Hi3DModeRequest(BaseModel):
    mode: str
    face_count: int = 2_000_000
    output_format: str = "glb"
    number_colors: int = 4
    part_count: int = 2
    joint_style: str = "dovetail"
    callback_url: str | None = None


@app.post("/v1/providers/hi3d/mode-fields")
def hi3d_mode_fields(req: Hi3DModeRequest):
    try:
        if req.mode == "portrait":
            return portrait_task_fields(face_count=req.face_count, output_format=req.output_format, callback_url=req.callback_url)
        if req.mode == "relief":
            return relief_task_fields(output_format=req.output_format if req.output_format in {"exr", "png"} else "exr", callback_url=req.callback_url)
        if req.mode == "multicolor":
            return multicolor_task_fields(number_colors=req.number_colors, face_count=req.face_count, callback_url=req.callback_url)
        if req.mode == "print_split":
            return print_split_task_fields(part_count=req.part_count, joint_style=req.joint_style, face_count=req.face_count, callback_url=req.callback_url)
        raise HTTPException(status_code=422, detail=f"Unknown Hi3D mode: {req.mode!r}")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


# --- Meshy live preview->refine execution -------------------------------
# Unlike everything else in this file, this performs real outbound HTTP
# calls with a real wall-clock polling loop -- it needs live MESHY_API_KEY
# credentials to do anything, so it doesn't fit compile_plan's synchronous,
# credential-free planning model (see app/pipeline/planner.py). Exposed as
# its own endpoint instead, reading the credential from the environment via
# the same pattern app/providers/auth.py already establishes.

from app.providers.execution import api_key_from_env
from app.providers.meshy import MeshyClient
from app.providers.meshy_pipeline import run_preview_refine


class MeshyPreviewRefineRequest(BaseModel):
    prompt: str
    geometry_resolution: str = "4k"
    texture_resolution: str = "8k"
    enable_pbr: bool = True
    poll_interval_seconds: float = 2.0
    max_polls: int = 150


@app.post("/v1/providers/meshy/preview-refine")
def meshy_preview_refine(req: MeshyPreviewRefineRequest):
    try:
        api_key = api_key_from_env("MESHY_API_KEY")
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    client = MeshyClient(api_key)
    return run_preview_refine(
        client, req.prompt,
        geometry_resolution=req.geometry_resolution,
        texture_resolution=req.texture_resolution,
        enable_pbr=req.enable_pbr,
        poll_interval_seconds=req.poll_interval_seconds,
        max_polls=req.max_polls,
    )


# --- Tripo / Hi3D live single-task execution -----------------------------
# Parity with the Meshy endpoint above: Tripo and Hi3D are single-phase
# (one submit, one poll to terminal) rather than Meshy's two-phase preview
# -> refine chain, so they share app/providers/single_task_pipeline.py
# instead of needing their own driver module.

from app.providers.hi3d import Hi3DClient
from app.providers.single_task_pipeline import run_single_task
from app.providers.tripo import TripoClient


class TripoGenerateRequest(BaseModel):
    mode: str  # "text" or "image"
    prompt: str | None = None
    input_ref: str | None = None
    poll_interval_seconds: float = 2.0
    max_polls: int = 150


@app.post("/v1/providers/tripo/generate")
def tripo_generate(req: TripoGenerateRequest):
    try:
        api_key = api_key_from_env("TRIPO_API_KEY")
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    client = TripoClient(api_key)
    if req.mode == "text":
        if not req.prompt:
            raise HTTPException(status_code=422, detail="mode='text' requires a prompt")
        submit = lambda: client.create_text(req.prompt)
    elif req.mode == "image":
        if not req.input_ref:
            raise HTTPException(status_code=422, detail="mode='image' requires input_ref")
        submit = lambda: client.create_image(req.input_ref)
    else:
        raise HTTPException(status_code=422, detail=f"Unknown Tripo mode: {req.mode!r}")
    return run_single_task(submit, client.query, poll_interval_seconds=req.poll_interval_seconds, max_polls=req.max_polls)


class Hi3DGenerateRequest(BaseModel):
    image_path: str
    face_count: int = 5_000_000
    output_format: str = "glb"
    poll_interval_seconds: float = 2.0
    max_polls: int = 150


@app.post("/v1/providers/hi3d/generate")
def hi3d_generate(req: Hi3DGenerateRequest):
    try:
        api_key = api_key_from_env("HI3D_API_KEY")
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    # Validated up front, not inside run_single_task: that function catches
    # every exception raised during submit() and folds it into a soft-fail
    # receipt (HTTP 200, status="failed") -- correct for a genuine
    # provider-side failure after submission, but wrong for a missing local
    # input file, which is a caller error and should be a distinct 404 like
    # every other file-path endpoint in this module. Verified this
    # distinction actually matters by testing run_single_task's real
    # behavior before relying on it, rather than assuming a wrapping
    # try/except around the call would ever fire (it would not: the
    # FileNotFoundError never leaves run_single_task).
    if not Path(req.image_path).is_file():
        raise HTTPException(status_code=404, detail=f"{req.image_path} does not exist")
    client = Hi3DClient(api_key)

    def submit():
        task_id, _plan = client.create_image_file(req.image_path, face_count=req.face_count, output_format=req.output_format)
        return task_id

    return run_single_task(submit, client.query, poll_interval_seconds=req.poll_interval_seconds, max_polls=req.max_polls)
