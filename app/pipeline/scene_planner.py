from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, Field

from app.core.models import HardwareProfile, PolicyDecision
from app.core.scene_models import SceneSpec
from app.core.scene_policy import evaluate_scene_policy


class SceneBudget(BaseModel):
    total_viewport_triangles: int
    total_hero_triangles: int
    instance_count: int
    hardware_scene_cap: int
    over_budget: bool
    notes: list[str] = Field(default_factory=list)


class ScenePipelinePlan(BaseModel):
    policy: PolicyDecision
    scene_manifest_hash: str | None = None
    budget: SceneBudget | None = None
    stages: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _hardware_scene_cap(hw: HardwareProfile) -> int:
    # Same conservative planning heuristic as per-character hero budgeting
    # (app/pipeline/planner.py::_hardware_hero_cap), applied to the WHOLE scene's
    # combined dense-geometry load instead of a single asset. A scene's cap is
    # not simply "hero cap x instance count": it's still bounded by this one
    # machine's RAM/VRAM, which is exactly why crowds/vast worlds need LOD and
    # streaming rather than every instance resident at full hero density at once.
    ram_cap = int(hw.ram_gb * 1_000_000)
    vram_cap = int(hw.vram_gb * 1_500_000)
    return max(2_000_000, min(200_000_000, ram_cap, vram_cap))


def scene_budget(scene: SceneSpec, hw: HardwareProfile) -> SceneBudget:
    viewport_total = sum(a.viewport_triangles or 0 for a in scene.assets)
    hero_total = sum(a.hero_source_triangles or 0 for a in scene.assets)
    cap = _hardware_scene_cap(hw)
    over = hero_total > cap
    notes = []
    if over:
        notes.append(
            f"Combined hero-source triangle load ({hero_total:,}) exceeds the "
            f"hardware-aware scene cap ({cap:,}); consider LOD swaps, instancing, "
            "streaming, or splitting the scene into loadable cells."
        )
    return SceneBudget(
        total_viewport_triangles=viewport_total,
        total_hero_triangles=hero_total,
        instance_count=len(scene.assets),
        hardware_scene_cap=cap,
        over_budget=over,
        notes=notes,
    )


def scene_manifest_hash(scene: SceneSpec) -> str:
    # Deterministic identity for a scene's composition (assets + transforms +
    # lighting), independent of Python dict/set iteration order: identical
    # composition -> identical hash, any change -> a different hash. Mirrors the
    # determinism discipline already used for character release manifests
    # (app/release/canonical.py, app/release/reproducibility.py).
    payload = scene.model_dump(mode="json")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def compile_scene_plan(scene: SceneSpec, hw: HardwareProfile) -> ScenePipelinePlan:
    policy = evaluate_scene_policy(scene)
    if not policy.allowed:
        return ScenePipelinePlan(policy=policy)

    budget = scene_budget(scene, hw)
    stages = [
        "scene_spec",
        "asset_resolution",  # resolve each instance's asset_sha256 against content-addressed storage
        "placement_validation",
        "lighting_environment",
        "budget_check",
        "scene_assembly_blender",
        "render_preview",
        "render_offline",
        "export_validation",
    ]
    return ScenePipelinePlan(
        policy=policy,
        scene_manifest_hash=scene_manifest_hash(scene),
        budget=budget,
        stages=stages,
        warnings=list(budget.notes),
    )
