from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from app.providers.execution import CanonicalTaskStatus, ProviderTaskSnapshot


@dataclass(frozen=True)
class PollPolicy:
    interval_seconds: float = 2.0
    timeout_seconds: float = 900.0
    max_interval_seconds: float = 20.0
    backoff: float = 1.5


def poll_until_terminal(query: Callable[[str], ProviderTaskSnapshot], task_id: str, *, policy: PollPolicy | None = None, sleep: Callable[[float], None] = time.sleep) -> ProviderTaskSnapshot:
    policy = policy or PollPolicy()
    started = time.monotonic()
    interval = policy.interval_seconds
    while True:
        snapshot = query(task_id)
        if snapshot.terminal:
            return snapshot
        if time.monotonic() - started >= policy.timeout_seconds:
            return snapshot.model_copy(update={"error": "Polling timeout before terminal provider state"})
        sleep(interval)
        interval = min(policy.max_interval_seconds, interval * policy.backoff)


def callback_requires_requery(provider: str) -> bool:
    # Tripo has a documented HMAC signature scheme. Meshy/Hi3D callbacks are useful for wakeups,
    # but this build independently re-queries their API before accepting terminal state.
    return provider.lower() in {"meshy", "hi3d", "hitem3d"}
