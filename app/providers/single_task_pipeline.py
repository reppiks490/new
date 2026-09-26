from __future__ import annotations

import time
from typing import Callable

from pydantic import BaseModel

from app.providers.execution import CanonicalTaskStatus, ProviderTaskSnapshot


class SingleTaskReceipt(BaseModel):
    task_id: str = ""
    snapshot: ProviderTaskSnapshot | None = None
    status: str = "pending"
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded"


def poll_to_terminal(
    query: Callable[[str], ProviderTaskSnapshot],
    task_id: str,
    *,
    poll_interval_seconds: float = 2.0,
    max_polls: int = 150,
    sleep: Callable[[float], None] = time.sleep,
) -> ProviderTaskSnapshot:
    """Shared poll-to-terminal loop. Extracted here so single-phase
    providers (Tripo, Hi3D: one submit, one poll) don't duplicate the same
    logic app/providers/meshy_pipeline.py already needed for its two-phase
    chain -- that module now imports this instead of keeping its own copy.
    """
    snapshot = query(task_id)
    polls = 0
    while not snapshot.terminal and polls < max_polls:
        sleep(poll_interval_seconds)
        snapshot = query(task_id)
        polls += 1
    return snapshot


def run_single_task(
    submit: Callable[[], str],
    query: Callable[[str], ProviderTaskSnapshot],
    *,
    poll_interval_seconds: float = 2.0,
    max_polls: int = 150,
    sleep: Callable[[float], None] = time.sleep,
) -> SingleTaskReceipt:
    """Drive a single-phase provider task end to end: submit, poll to
    terminal, report success/failure. For providers whose generation is one
    task (Tripo, Hi3D) rather than Meshy's two-phase preview->refine chain.
    """
    receipt = SingleTaskReceipt()
    try:
        task_id = submit()
        receipt.task_id = task_id
        snapshot = poll_to_terminal(
            query, task_id,
            poll_interval_seconds=poll_interval_seconds, max_polls=max_polls, sleep=sleep,
        )
        receipt.snapshot = snapshot
        if snapshot.status == CanonicalTaskStatus.SUCCEEDED:
            receipt.status = "succeeded"
        else:
            receipt.status = "failed"
            receipt.error = snapshot.error or f"task ended in status {snapshot.status.value}"
        return receipt
    except Exception as exc:
        receipt.status = "failed"
        receipt.error = str(exc)
        return receipt
