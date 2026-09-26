from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, Field

from app.workers.execution_evidence import ExecutionEvidence, ExecutionMode, sha256_file


DEFAULT_REQUIRED_LIVE_STAGES = [
    'provider_ingest',
    'candidate_promotion',
    'blender',
    'qa',
    'export',
]


class CanonicalArtifact(BaseModel):
    name: str
    kind: str
    size_bytes: int
    sha256: str
    path: str | None = None


class CanonicalReleaseManifest(BaseModel):
    schema_version: str = 'character3d-canonical-release-v1'
    job_id: str
    created_at_unix: int
    artifacts: list[CanonicalArtifact]
    evidence: list[ExecutionEvidence]
    production_gate_passed: bool
    required_live_stages: list[str]
    releasable: bool
    blockers: list[str] = Field(default_factory=list)
    manifest_sha256: str


class CanonicalReleaseEvaluation(BaseModel):
    releasable: bool
    blockers: list[str] = Field(default_factory=list)
    live_stages: list[str] = Field(default_factory=list)
    non_live_stages: list[str] = Field(default_factory=list)


def artifact_from_path(path: str | Path, *, kind: str, name: str | None = None) -> CanonicalArtifact:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(p)
    return CanonicalArtifact(
        name=name or p.name,
        kind=kind,
        size_bytes=p.stat().st_size,
        sha256=sha256_file(p),
        path=str(p),
    )


def evaluate_canonical_release(
    evidence: Iterable[ExecutionEvidence],
    *,
    production_gate_passed: bool,
    required_live_stages: list[str] | None = None,
) -> CanonicalReleaseEvaluation:
    required = required_live_stages or list(DEFAULT_REQUIRED_LIVE_STAGES)
    ev = list(evidence)
    latest: dict[str, ExecutionEvidence] = {}
    for item in ev:
        latest[item.stage] = item

    blockers: list[str] = []
    live: list[str] = []
    non_live: list[str] = []
    if not production_gate_passed:
        blockers.append('Composite production gate did not pass.')

    for stage in required:
        item = latest.get(stage)
        if item is None:
            blockers.append(f'Missing execution evidence for required stage: {stage}.')
            non_live.append(stage)
            continue
        if item.mode != ExecutionMode.LIVE:
            blockers.append(f'Required stage {stage} is {item.mode.value}, not live.')
            non_live.append(stage)
        elif not item.success:
            blockers.append(f'Required live stage {stage} did not succeed.')
            non_live.append(stage)
        else:
            live.append(stage)

    return CanonicalReleaseEvaluation(
        releasable=not blockers,
        blockers=blockers,
        live_stages=live,
        non_live_stages=non_live,
    )


def _manifest_digest(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str).encode('utf-8')).hexdigest()


def compile_canonical_release_manifest(
    job_id: str,
    artifacts: Iterable[CanonicalArtifact],
    evidence: Iterable[ExecutionEvidence],
    *,
    production_gate_passed: bool,
    required_live_stages: list[str] | None = None,
    created_at_unix: int | None = None,
) -> CanonicalReleaseManifest:
    artifact_list = sorted(list(artifacts), key=lambda x: (x.kind, x.name, x.sha256))
    evidence_list = list(evidence)
    required = required_live_stages or list(DEFAULT_REQUIRED_LIVE_STAGES)
    evaluation = evaluate_canonical_release(
        evidence_list,
        production_gate_passed=production_gate_passed,
        required_live_stages=required,
    )
    created = int(time.time() if created_at_unix is None else created_at_unix)
    base = {
        'schema_version': 'character3d-canonical-release-v1',
        'job_id': job_id,
        'created_at_unix': created,
        'artifacts': [x.model_dump(mode='json') for x in artifact_list],
        'evidence': [x.model_dump(mode='json') for x in evidence_list],
        'production_gate_passed': production_gate_passed,
        'required_live_stages': required,
        'releasable': evaluation.releasable,
        'blockers': evaluation.blockers,
    }
    return CanonicalReleaseManifest(**base, manifest_sha256=_manifest_digest(base))


def write_canonical_manifest(manifest: CanonicalReleaseManifest, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(manifest.model_dump(mode='json'), indent=2, sort_keys=True), encoding='utf-8')
    return p


def verify_canonical_manifest(manifest: CanonicalReleaseManifest) -> bool:
    base = manifest.model_dump(mode='json', exclude={'manifest_sha256'})
    return _manifest_digest(base) == manifest.manifest_sha256
