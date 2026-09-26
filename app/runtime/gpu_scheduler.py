from __future__ import annotations

from pydantic import BaseModel, Field


class GPUWorker(BaseModel):
    worker_id: str
    vendor: str
    backend: str
    total_vram_gb: float = Field(gt=0)
    free_vram_gb: float = Field(ge=0)
    queue_depth: int = Field(default=0, ge=0)
    healthy: bool = True
    capabilities: set[str] = Field(default_factory=set)


class GPUJobRequest(BaseModel):
    min_vram_gb: float = Field(default=8, gt=0)
    preferred_backend: str | None = None
    required_capabilities: set[str] = Field(default_factory=set)
    reserve_vram_gb: float = Field(default=2, ge=0)


class SchedulingDecision(BaseModel):
    worker: GPUWorker
    score: float
    reasons: list[str]


def choose_gpu_worker(workers: list[GPUWorker], job: GPUJobRequest) -> SchedulingDecision:
    eligible: list[SchedulingDecision] = []
    for worker in workers:
        if not worker.healthy:
            continue
        usable=max(0.0, worker.free_vram_gb-job.reserve_vram_gb)
        if usable < job.min_vram_gb:
            continue
        if not job.required_capabilities.issubset(worker.capabilities):
            continue
        score=usable - 1.5*worker.queue_depth
        reasons=[f'{usable:.1f} GiB usable VRAM after reserve',f'queue depth {worker.queue_depth}']
        if job.preferred_backend and worker.backend.lower()==job.preferred_backend.lower():
            score += 8.0
            reasons.append(f'preferred backend {worker.backend}')
        if worker.total_vram_gb >= 48:
            score += 2.0
            reasons.append('high-memory tier')
        eligible.append(SchedulingDecision(worker=worker,score=round(score,4),reasons=reasons))
    if not eligible:
        raise RuntimeError('No healthy GPU worker satisfies this job request')
    eligible.sort(key=lambda d:(d.score,d.worker.free_vram_gb,-d.worker.queue_depth), reverse=True)
    return eligible[0]
