from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

from app.providers.execution import (
    CanonicalTaskStatus,
    HttpxTransport,
    ProviderExecutionError,
    ProviderTaskSnapshot,
    RemoteAsset,
    Transport,
    bearer_headers,
)
from app.providers.models import ProviderId

BASE_URL = "https://openapi.tripo3d.ai/v3"
TRUSTED_ASSET_HOSTS = {"cdn.tripo3d.ai", "tripo3d.ai"}


def text_generation_request(
    prompt: str,
    *,
    face_limit: int = 2_000_000,
    detailed_geometry: bool = True,
    detailed_texture: bool = True,
    pbr: bool = True,
    model: str = "v3.1-20260211",
) -> dict[str, Any]:
    if not 1 <= face_limit <= 2_000_000:
        raise ValueError("Tripo H3.1 face_limit must be 1..2,000,000")
    if len(prompt) > 1024:
        raise ValueError("Tripo text prompt is limited to 1024 characters")
    return {
        "prompt": prompt,
        "model": model,
        "face_limit": face_limit,
        "geometry_quality": "detailed" if detailed_geometry else "standard",
        "texture": True,
        "pbr": pbr,
        "texture_quality": "detailed" if detailed_texture else "standard",
    }


def image_generation_request(
    input_ref: str,
    *,
    face_limit: int = 2_000_000,
    detailed_geometry: bool = True,
    detailed_texture: bool = True,
    pbr: bool = True,
    model: str = "v3.1-20260211",
) -> dict[str, Any]:
    if not input_ref:
        raise ValueError("input_ref is required")
    if not 1 <= face_limit <= 2_000_000:
        raise ValueError("Tripo H3.1 face_limit must be 1..2,000,000")
    return {
        "input": input_ref,
        "model": model,
        "face_limit": face_limit,
        "geometry_quality": "detailed" if detailed_geometry else "standard",
        "texture": True,
        "pbr": pbr,
        "texture_quality": "detailed" if detailed_texture else "standard",
    }


def _normalize_status(raw: str | None) -> CanonicalTaskStatus:
    value = (raw or "").lower()
    return {
        "queued": CanonicalTaskStatus.QUEUED,
        "running": CanonicalTaskStatus.RUNNING,
        "success": CanonicalTaskStatus.SUCCEEDED,
        "failed": CanonicalTaskStatus.FAILED,
        "cancelled": CanonicalTaskStatus.CANCELLED,
    }.get(value, CanonicalTaskStatus.UNKNOWN)


def parse_task(payload: dict[str, Any]) -> ProviderTaskSnapshot:
    data = payload.get("data", payload)
    output = data.get("output") or {}
    assets: list[RemoteAsset] = []
    if output.get("model_url"):
        assets.append(RemoteAsset(kind="model", url=output["model_url"], format="glb"))
    if output.get("rendered_image_url"):
        assets.append(RemoteAsset(kind="preview", url=output["rendered_image_url"], format="png"))
    err = data.get("error")
    if isinstance(err, dict):
        err = err.get("message") or json.dumps(err, sort_keys=True)
    return ProviderTaskSnapshot(
        provider=ProviderId.TRIPO,
        task_id=str(data.get("task_id", "")),
        status=_normalize_status(data.get("status")),
        raw_status=data.get("status"),
        progress=data.get("progress"),
        assets=assets,
        credits_consumed=data.get("credits_consumed"),
        error=err,
        metadata={"type": data.get("type")},
    )


class TripoClient:
    def __init__(self, api_key: str, *, transport: Transport | None = None):
        self.api_key = api_key
        self.transport = transport or HttpxTransport()

    @property
    def headers(self) -> dict[str, str]:
        return {**bearer_headers(self.api_key), "Content-Type": "application/json"}

    def _post_task(self, path: str, payload: dict[str, Any]) -> str:
        r = self.transport.request("POST", BASE_URL + path, headers=self.headers, json=payload)
        body = r.json()
        if r.status_code >= 400 or body.get("code", 0) != 0:
            raise ProviderExecutionError(ProviderId.TRIPO, body.get("message", "Tripo task creation failed"), status_code=r.status_code, payload=body)
        return str(body["data"]["task_id"])

    def create_text(self, prompt: str, **kwargs: Any) -> str:
        return self._post_task("/generation/text-to-model", text_generation_request(prompt, **kwargs))

    def create_image(self, input_ref: str, **kwargs: Any) -> str:
        return self._post_task("/generation/image-to-model", image_generation_request(input_ref, **kwargs))

    def query(self, task_id: str) -> ProviderTaskSnapshot:
        r = self.transport.request("GET", f"{BASE_URL}/tasks/{task_id}", headers=bearer_headers(self.api_key))
        body = r.json()
        if r.status_code >= 400 or body.get("code", 0) != 0:
            raise ProviderExecutionError(ProviderId.TRIPO, body.get("message", "Tripo task query failed"), status_code=r.status_code, payload=body)
        return parse_task(body)


def verify_webhook_signature(raw_body: bytes, signature_header: str, secret: str, *, now: int | None = None, tolerance_seconds: int = 300) -> bool:
    try:
        parts = dict(piece.split("=", 1) for piece in signature_header.split(",") if "=" in piece)
        timestamp = int(parts.get("t", "0"))
        supplied = parts.get("v1", "")
    except (TypeError, ValueError):
        return False
    now = int(time.time()) if now is None else int(now)
    if not supplied or abs(now - timestamp) > tolerance_seconds:
        return False
    signed = str(timestamp).encode("utf-8") + b"." + raw_body
    expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, supplied)
