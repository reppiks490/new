from __future__ import annotations

import hashlib
import json
import time
from enum import Enum
from typing import Any, Callable

from pydantic import BaseModel, Field


class ProductionStage(str, Enum):
    PROVIDER_SUBMIT = 'provider_submit'
    PROVIDER_TERMINAL = 'provider_terminal'
    ASSET_INGEST = 'asset_ingest'
    CANDIDATE_PROMOTION = 'candidate_promotion'
    BLENDER_REPAIR = 'blender_repair'
    BAKE = 'bake'
    QA = 'qa'
    EXPORT = 'export'
    ATTEST = 'attest'


_STAGE_ORDER = list(ProductionStage)


class StageReceipt(BaseModel):
    stage: ProductionStage
    status: str
    started_at: float
    finished_at: float
    payload_sha256: str
    previous_sha256: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class ProductionChainPlan(BaseModel):
    job_id: str
    provider: str
    authenticated: bool
    stages: list[ProductionStage]
    blockers: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ProductionChainReport(BaseModel):
    job_id: str
    status: str
    completed_stages: list[ProductionStage]
    receipts: list[StageReceipt]
    final_sha256: str | None = None
    error: str | None = None


def compile_production_chain_plan(job_id: str, provider: str, *, authenticated: bool, require_repair: bool = True, require_bake: bool = True) -> ProductionChainPlan:
    stages = [
        ProductionStage.PROVIDER_SUBMIT,
        ProductionStage.PROVIDER_TERMINAL,
        ProductionStage.ASSET_INGEST,
        ProductionStage.CANDIDATE_PROMOTION,
    ]
    if require_repair:
        stages.append(ProductionStage.BLENDER_REPAIR)
    if require_bake:
        stages.append(ProductionStage.BAKE)
    stages.extend([ProductionStage.QA, ProductionStage.EXPORT, ProductionStage.ATTEST])
    blockers: list[str] = []
    if not authenticated:
        blockers.append('Provider execution requires explicit authenticated credentials before live submission.')
    return ProductionChainPlan(
        job_id=job_id,
        provider=provider,
        authenticated=authenticated,
        stages=stages,
        blockers=blockers,
        notes=['Remote provider output remains untrusted until asset hashing, local QA, and canonical promotion succeed.'],
    )


def _receipt_hash(stage: ProductionStage, result: dict[str, Any], previous: str | None) -> str:
    payload = {'stage': stage.value, 'result': result, 'previous_sha256': previous}
    blob = json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str).encode('utf-8')
    return hashlib.sha256(blob).hexdigest()


def run_production_chain(plan: ProductionChainPlan, handlers: dict[ProductionStage, Callable[[], dict[str, Any]]]) -> ProductionChainReport:
    if plan.blockers:
        return ProductionChainReport(job_id=plan.job_id, status='blocked', completed_stages=[], receipts=[], error='; '.join(plan.blockers))
    receipts: list[StageReceipt] = []
    previous: str | None = None
    completed: list[ProductionStage] = []
    for stage in plan.stages:
        started = time.time()
        handler = handlers.get(stage)
        if handler is None:
            return ProductionChainReport(
                job_id=plan.job_id, status='failed', completed_stages=completed, receipts=receipts,
                final_sha256=previous, error=f'missing handler for stage {stage.value}',
            )
        try:
            result = handler() or {}
            if result.get('passed') is False or result.get('accepted') is False or result.get('status') in {'failed', 'cancelled'}:
                raise RuntimeError(result.get('error') or f'stage {stage.value} rejected its result')
            digest = _receipt_hash(stage, result, previous)
            finished = time.time()
            receipts.append(StageReceipt(
                stage=stage, status='succeeded', started_at=started, finished_at=finished,
                payload_sha256=digest, previous_sha256=previous, result=result,
            ))
            previous = digest
            completed.append(stage)
        except Exception as exc:
            finished = time.time()
            error_result = {'error': str(exc)}
            digest = _receipt_hash(stage, error_result, previous)
            receipts.append(StageReceipt(
                stage=stage, status='failed', started_at=started, finished_at=finished,
                payload_sha256=digest, previous_sha256=previous, result=error_result, error=str(exc),
            ))
            return ProductionChainReport(
                job_id=plan.job_id, status='failed', completed_stages=completed, receipts=receipts,
                final_sha256=digest, error=str(exc),
            )
    return ProductionChainReport(job_id=plan.job_id, status='succeeded', completed_stages=completed, receipts=receipts, final_sha256=previous)
