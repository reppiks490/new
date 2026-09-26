from __future__ import annotations

from typing import Any

from app.providers.execution import CanonicalTaskStatus, HttpxTransport, ProviderExecutionError, ProviderTaskSnapshot, RemoteAsset, Transport, bearer_headers
from app.providers.models import ProviderId

BASE_URL = "https://api.meshy.ai"
TRUSTED_ASSET_HOSTS = {"assets.meshy.ai", "meshy.ai"}


def text_preview_request(prompt: str, *, geometry_resolution: str = "4k", target_format: str = "glb") -> dict:
    if geometry_resolution not in {"standard", "2k", "4k"}:
        raise ValueError("geometry_resolution must be standard, 2k, or 4k")
    return {
        "mode": "preview",
        "prompt": prompt,
        "ai_model": "meshy-7.1",
        "geometry_resolution": geometry_resolution,
        "should_remesh": False,
        "target_formats": [target_format],
    }


def refine_request(preview_task_id: str, *, texture_resolution: str = "8k", enable_pbr: bool = True) -> dict:
    if texture_resolution not in {"2k", "4k", "8k"}:
        raise ValueError("texture_resolution must be 2k, 4k, or 8k")
    return {
        "mode": "refine",
        "preview_task_id": preview_task_id,
        "ai_model": "meshy-7.1",
        "texture_resolution": texture_resolution,
        "enable_pbr": enable_pbr,
        "target_formats": ["glb"],
    }


def image_to_3d_request(image_url: str, *, geometry_resolution: str = "4k", texture_resolution: str = "8k", enable_pbr: bool = True) -> dict[str, Any]:
    if geometry_resolution not in {"standard", "2k", "4k"}:
        raise ValueError("geometry_resolution must be standard, 2k, or 4k")
    if texture_resolution not in {"2k", "4k", "8k"}:
        raise ValueError("texture_resolution must be 2k, 4k, or 8k")
    return {
        "image_url": image_url,
        "ai_model": "meshy-7.1",
        "model_type": "standard",
        "geometry_resolution": geometry_resolution,
        "should_texture": True,
        "enable_pbr": enable_pbr,
        "texture_resolution": texture_resolution,
        "image_enhancement": True,
        "target_formats": ["glb", "fbx"],
    }


def multi_image_request(image_urls: list[str], *, geometry_resolution: str = "2k") -> dict[str, Any]:
    if not 1 <= len(image_urls) <= 4:
        raise ValueError("Meshy multi-image accepts 1..4 images")
    if geometry_resolution not in {"standard", "2k"}:
        raise ValueError("Meshy multi-image currently supports standard or 2k geometry only")
    return {
        "image_urls": image_urls,
        "ai_model": "meshy-7.1",
        "geometry_resolution": geometry_resolution,
        "should_texture": True,
        "enable_pbr": True,
        "texture_resolution": "8k",
        "target_formats": ["glb", "fbx"],
    }


def smart_topology_request(model_url: str, target_polycount: int = 15_000) -> dict:
    if not 100 <= target_polycount <= 15_000:
        raise ValueError("Meshy Smart Topology target_polycount must be 100..15000")
    return {
        "model_url": model_url,
        "model_type": "smart-topology",
        "ai_model": "meshy-t2",
        "target_polycount": target_polycount,
    }


def rigging_compatible(face_count: int, *, textured: bool = True, humanoid: bool = True) -> bool:
    return textured and humanoid and face_count <= 300_000


def _normalize_status(raw: str | None) -> CanonicalTaskStatus:
    value = (raw or "").upper()
    return {
        "PENDING": CanonicalTaskStatus.QUEUED,
        "IN_PROGRESS": CanonicalTaskStatus.RUNNING,
        "SUCCEEDED": CanonicalTaskStatus.SUCCEEDED,
        "FAILED": CanonicalTaskStatus.FAILED,
        "CANCELED": CanonicalTaskStatus.CANCELLED,
    }.get(value, CanonicalTaskStatus.UNKNOWN)


def parse_task(payload: dict[str, Any]) -> ProviderTaskSnapshot:
    assets: list[RemoteAsset] = []
    for fmt, url in (payload.get("model_urls") or {}).items():
        if url:
            assets.append(RemoteAsset(kind="model", url=url, format=fmt))
    if payload.get("thumbnail_url"):
        assets.append(RemoteAsset(kind="preview", url=payload["thumbnail_url"], format="png"))
    for i, maps in enumerate(payload.get("texture_urls") or []):
        for channel, url in maps.items():
            if url:
                assets.append(RemoteAsset(kind=f"texture:{channel}:{i}", url=url, format="png"))
    task_error = payload.get("task_error") or {}
    error = task_error.get("message") if isinstance(task_error, dict) else str(task_error)
    return ProviderTaskSnapshot(
        provider=ProviderId.MESHY,
        task_id=str(payload.get("id", "")),
        status=_normalize_status(payload.get("status")),
        raw_status=payload.get("status"),
        progress=payload.get("progress"),
        assets=assets,
        credits_consumed=payload.get("consumed_credits"),
        error=error or None,
        metadata={"type": payload.get("type")},
    )


class MeshyClient:
    def __init__(self, api_key: str, *, transport: Transport | None = None):
        self.api_key = api_key
        self.transport = transport or HttpxTransport()

    @property
    def headers(self) -> dict[str, str]:
        return {**bearer_headers(self.api_key), "Content-Type": "application/json"}

    def _create(self, path: str, payload: dict[str, Any]) -> str:
        r = self.transport.request("POST", BASE_URL + path, headers=self.headers, json=payload)
        body = r.json()
        if r.status_code >= 400:
            raise ProviderExecutionError(ProviderId.MESHY, body.get("message", "Meshy task creation failed"), status_code=r.status_code, payload=body)
        task_id = body.get("result") or body.get("id")
        if not task_id:
            raise ProviderExecutionError(ProviderId.MESHY, "Meshy response omitted task id", status_code=r.status_code, payload=body)
        return str(task_id)

    def create_text_preview(self, prompt: str, **kwargs: Any) -> str:
        return self._create("/openapi/v2/text-to-3d", text_preview_request(prompt, **kwargs))

    def create_text_refine(self, preview_task_id: str, **kwargs: Any) -> str:
        return self._create("/openapi/v2/text-to-3d", refine_request(preview_task_id, **kwargs))

    def create_image(self, image_url: str, **kwargs: Any) -> str:
        return self._create("/openapi/v1/image-to-3d", image_to_3d_request(image_url, **kwargs))

    def create_multi_image(self, image_urls: list[str], **kwargs: Any) -> str:
        return self._create("/openapi/v1/multi-image-to-3d", multi_image_request(image_urls, **kwargs))

    def query_text(self, task_id: str) -> ProviderTaskSnapshot:
        return self._query(f"/openapi/v2/text-to-3d/{task_id}")

    def query_image(self, task_id: str) -> ProviderTaskSnapshot:
        return self._query(f"/openapi/v1/image-to-3d/{task_id}")

    def _query(self, path: str) -> ProviderTaskSnapshot:
        r = self.transport.request("GET", BASE_URL + path, headers=bearer_headers(self.api_key))
        body = r.json()
        if r.status_code >= 400:
            raise ProviderExecutionError(ProviderId.MESHY, body.get("message", "Meshy task query failed"), status_code=r.status_code, payload=body)
        return parse_task(body)
