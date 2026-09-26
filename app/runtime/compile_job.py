from __future__ import annotations

from pathlib import Path
from app.core.models import CharacterSpec, HardwareProfile
from app.pipeline.planner import compile_plan
from app.runtime.jobs import JobManifest, StageRecord, stable_plan_hash


def compile_job_manifest(
    spec: CharacterSpec,
    hardware: HardwareProfile,
    workspace: str | Path,
) -> JobManifest:
    plan = compile_plan(spec, hardware)
    plan_dict = plan.model_dump(mode="json")
    return JobManifest(
        plan_hash=stable_plan_hash(plan_dict),
        character=spec.model_dump(mode="json"),
        hardware=hardware.model_dump(mode="json"),
        stages=[StageRecord(name=s) for s in plan.stages],
        workspace=str(Path(workspace).resolve()),
    )
