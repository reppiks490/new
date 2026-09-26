from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel

from app.providers.execution import ProviderTaskSnapshot
from app.providers.hi3d import parse_task as parse_hi3d
from app.providers.ledger import ProviderLedger
from app.providers.meshy import parse_task as parse_meshy
from app.providers.models import ProviderId
from app.providers.tripo import parse_task as parse_tripo, verify_webhook_signature


class WebhookDecision(BaseModel):
    provider: ProviderId
    accepted: bool
    duplicate: bool = False
    cryptographically_verified: bool = False
    authoritative_terminal_state: bool = False
    requery_required: bool = True
    reason: str
    snapshot: ProviderTaskSnapshot | None = None


def _json_body(raw_body: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Webhook body is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("Webhook body must be a JSON object")
    return value


def accept_tripo_webhook(
    raw_body: bytes,
    *,
    signature_header: str,
    delivery_id: str,
    secret: str,
    ledger: ProviderLedger | None = None,
    now: int | None = None,
) -> WebhookDecision:
    if not verify_webhook_signature(raw_body, signature_header, secret, now=now):
        return WebhookDecision(
            provider=ProviderId.TRIPO,
            accepted=False,
            cryptographically_verified=False,
            authoritative_terminal_state=False,
            requery_required=True,
            reason="invalid Tripo webhook signature or replay window",
        )
    if not delivery_id:
        return WebhookDecision(
            provider=ProviderId.TRIPO,
            accepted=False,
            cryptographically_verified=True,
            reason="missing Tripo-Webhook-Delivery id",
        )
    if ledger and not ledger.record_delivery(ProviderId.TRIPO, delivery_id, raw_body):
        return WebhookDecision(
            provider=ProviderId.TRIPO,
            accepted=True,
            duplicate=True,
            cryptographically_verified=True,
            authoritative_terminal_state=False,
            requery_required=False,
            reason="duplicate signed Tripo delivery ignored",
        )
    payload = _json_body(raw_body)
    event_type = str(payload.get("type", ""))
    data = payload.get("data") or {}
    snapshot = parse_tripo({"data": data}) if event_type.startswith("task.") else None
    if snapshot and ledger:
        ledger.upsert_snapshot(snapshot)
    return WebhookDecision(
        provider=ProviderId.TRIPO,
        accepted=True,
        cryptographically_verified=True,
        authoritative_terminal_state=bool(snapshot and snapshot.terminal),
        requery_required=False,
        reason="signed Tripo task webhook accepted" if snapshot else "signed non-task Tripo event accepted",
        snapshot=snapshot,
    )


def accept_advisory_webhook(
    provider: ProviderId,
    raw_body: bytes,
    *,
    ledger: ProviderLedger | None = None,
    delivery_id: str | None = None,
) -> WebhookDecision:
    if provider not in {ProviderId.MESHY, ProviderId.HI3D}:
        raise ValueError("Advisory webhook path is only for Meshy or Hi3D")
    payload = _json_body(raw_body)
    parser = parse_meshy if provider == ProviderId.MESHY else parse_hi3d
    snapshot = parser(payload)
    # Neither referenced provider documentation currently defines a cryptographic webhook signature.
    # Use the callback only to wake the job; official task query remains authoritative.
    synthetic_id = delivery_id or hashlib.sha256(raw_body).hexdigest()
    duplicate = False
    if ledger:
        duplicate = not ledger.record_delivery(provider, synthetic_id, raw_body)
        if not duplicate:
            ledger.upsert_snapshot(snapshot)
    return WebhookDecision(
        provider=provider,
        accepted=True,
        duplicate=duplicate,
        cryptographically_verified=False,
        authoritative_terminal_state=False,
        requery_required=True,
        reason="advisory callback recorded; provider API re-query required before ingestion",
        snapshot=snapshot,
    )
