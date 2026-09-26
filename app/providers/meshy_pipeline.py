from __future__ import annotations

import time
from enum import Enum
from typing import Callable

from pydantic import BaseModel, Field

from app.providers.execution import CanonicalTaskStatus, ProviderTaskSnapshot
from app.providers.meshy import MeshyClient


class MeshyPipelineStage(str, Enum):
    PREVIEW_SUBMIT = "preview_submit"
    PREVIEW_POLL = "preview_poll"
    REFINE_SUBMIT = "refine_submit"
    REFINE_POLL = "refine_poll"


class MeshyPreviewRefineReceipt(BaseModel):
    preview_task_id: str = ""
    refine_task_id: str | None = None
    preview_snapshot: ProviderTaskSnapshot | None = None
    refine_snapshot: ProviderTaskSnapshot | None = None
    stage_log: list[str] = Field(default_factory=list)
    status: str = "pending"
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded"


def _poll_to_terminal(
    query: Callable[[str], ProviderTaskSnapshot],
    task_id: str,
    interval: float,
    max_polls: int,
    sleep: Callable[[float], None],
) -> ProviderTaskSnapshot:
    snapshot = query(task_id)
    polls = 0
    while not snapshot.terminal and polls < max_polls:
        sleep(interval)
        snapshot = query(task_id)
        polls += 1
    return snapshot


def run_preview_refine(
    client: MeshyClient,
    prompt: str,
    *,
    geometry_resolution: str = "4k",
    texture_resolution: str = "8k",
    enable_pbr: bool = True,
    poll_interval_seconds: float = 2.0,
    max_polls: int = 150,
    sleep: Callable[[float], None] = time.sleep,
) -> MeshyPreviewRefineReceipt:
    """Drive Meshy's documented two-phase preview -> refine task chain end to
    end. This is not a single provider task: the refine call requires the
    preview call's task_id, so app/pipeline/production_chain.py's generic
    single-submit/single-terminal stage model doesn't fit it. This is a
    dedicated, provider-specific driver instead of forcing that shape.

    A returned receipt with status="succeeded" means both HTTP task-creation
    calls and both polling loops actually reached a terminal SUCCEEDED status
    against whatever Transport the client was constructed with -- if that
    transport is real (HttpxTransport), this is live provider execution, not
    a planned/synthetic stage.
    """
    receipt = MeshyPreviewRefineReceipt()
    try:
        preview_task_id = client.create_text_preview(prompt, geometry_resolution=geometry_resolution)
        receipt.preview_task_id = preview_task_id
        receipt.stage_log.append(f"{MeshyPipelineStage.PREVIEW_SUBMIT.value}:{preview_task_id}")

        preview_snapshot = _poll_to_terminal(client.query_text, preview_task_id, poll_interval_seconds, max_polls, sleep)
        receipt.preview_snapshot = preview_snapshot
        receipt.stage_log.append(f"{MeshyPipelineStage.PREVIEW_POLL.value}:{preview_snapshot.status.value}")
        if preview_snapshot.status != CanonicalTaskStatus.SUCCEEDED:
            receipt.status = "failed"
            receipt.error = preview_snapshot.error or f"preview task ended in status {preview_snapshot.status.value}"
            return receipt

        refine_task_id = client.create_text_refine(preview_task_id, texture_resolution=texture_resolution, enable_pbr=enable_pbr)
        receipt.refine_task_id = refine_task_id
        receipt.stage_log.append(f"{MeshyPipelineStage.REFINE_SUBMIT.value}:{refine_task_id}")

        refine_snapshot = _poll_to_terminal(client.query_text, refine_task_id, poll_interval_seconds, max_polls, sleep)
        receipt.refine_snapshot = refine_snapshot
        receipt.stage_log.append(f"{MeshyPipelineStage.REFINE_POLL.value}:{refine_snapshot.status.value}")
        if refine_snapshot.status != CanonicalTaskStatus.SUCCEEDED:
            receipt.status = "failed"
            receipt.error = refine_snapshot.error or f"refine task ended in status {refine_snapshot.status.value}"
            return receipt

        receipt.status = "succeeded"
        return receipt
    except Exception as exc:
        receipt.status = "failed"
        receipt.error = str(exc)
        return receipt
