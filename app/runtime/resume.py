from __future__ import annotations

from dataclasses import dataclass
from app.providers.ledger import ProviderLedger
from app.providers.models import ProviderId

TERMINAL={'succeeded','failed','cancelled'}

@dataclass(frozen=True)
class ResumeDecision:
    action: str
    reason: str


def decide_resume(ledger: ProviderLedger, provider: ProviderId, task_id: str) -> ResumeDecision:
    row=ledger.get_task(provider, task_id)
    if row is None: return ResumeDecision('submit','No durable provider task exists.')
    status=str(row['status']).lower()
    if status == 'succeeded':
        assets=ledger.list_assets(provider, task_id)
        missing=[a for a in assets if not a.get('local_path') or not a.get('sha256')]
        return ResumeDecision('ingest' if missing else 'complete', 'Terminal success requires asset ingestion.' if missing else 'Verified assets already recorded.')
    if status in TERMINAL: return ResumeDecision('stop', f'Task is terminal: {status}.')
    return ResumeDecision('poll', f'Resume polling durable task in state {status}.')
