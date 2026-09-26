from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.providers.execution import CanonicalTaskStatus, HttpxTransport, ProviderExecutionError, ProviderTaskSnapshot, RemoteAsset, Transport, bearer_headers
from app.providers.models import ProviderId

BASE_URL = "https://api.hitem3d.ai"
TRUSTED_ASSET_HOSTS = {"hitem3d.ai", "hitem3dstatic.zaohaowu.net", "zaohao3d.com"}


@dataclass(frozen=True)
class Hi3DSubmissionPlan:
    requested_faces: int
    retry_faces: tuple[int, ...]
    resolution: str
    warning: str | None = None


def high_density_submission_plan(requested_faces: int = 5_000_000) -> Hi3DSubmissionPlan:
    if requested_faces < 100_000:
        raise ValueError("Hi3D documented face range begins at 100,000")
    requested_faces = min(requested_faces, 5_000_000)
    if requested_faces > 2_000_000:
        return Hi3DSubmissionPlan(
            requested_faces=requested_faces,
            retry_faces=(requested_faces, 2_000_000),
            resolution="2048master",
            warning=(
                "Hi3D parameter docs recommend up to 5M faces for 2048master, while an error table still "
                "mentions a 2M validation ceiling. Submit high target first, then fall back to 2M on validation rejection."
            ),
        )
    return Hi3DSubmissionPlan(requested_faces=requested_faces, retry_faces=(requested_faces,), resolution="2048quality")


def image_task_fields(*, face_count: int = 5_000_000, pbr: bool = True, output_format: str = "glb", callback_url: str | None = None, model: str = "hi3dv3.0") -> dict:
    plan = high_density_submission_plan(face_count)
    format_map = {"obj": 1, "glb": 2, "stl": 3, "fbx": 4, "usdz": 5, "3mf": 6}
    if output_format not in format_map:
        raise ValueError(f"Unsupported Hi3D output format: {output_format}")
    data = {
        "request_type": "3",
        "resolution": plan.resolution,
        "face": str(plan.requested_faces),
        "model": model,
        "format": str(format_map[output_format]),
        "pbr": "1" if pbr else "0",
        "rmbg": "1",
        "shading": "0.5",
    }
    if callback_url:
        data["callback_url"] = callback_url
    return data


def _normalize_status(raw: str | None) -> CanonicalTaskStatus:
    value = (raw or "").lower()
    return {
        "queued": CanonicalTaskStatus.QUEUED,
        "pending": CanonicalTaskStatus.QUEUED,
        "running": CanonicalTaskStatus.RUNNING,
        "processing": CanonicalTaskStatus.RUNNING,
        "success": CanonicalTaskStatus.SUCCEEDED,
        "failed": CanonicalTaskStatus.FAILED,
        "cancelled": CanonicalTaskStatus.CANCELLED,
        "canceled": CanonicalTaskStatus.CANCELLED,
    }.get(value, CanonicalTaskStatus.UNKNOWN)


def _collect_urls(obj: Any, prefix: str = "output") -> list[RemoteAsset]:
    out: list[RemoteAsset] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            out.extend(_collect_urls(value, f"{prefix}:{key}"))
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            out.extend(_collect_urls(value, f"{prefix}:{i}"))
    elif isinstance(obj, str) and obj.startswith("https://"):
        suffix = obj.split("?", 1)[0].rsplit(".", 1)
        fmt = suffix[-1].lower() if len(suffix) == 2 else None
        out.append(RemoteAsset(kind=prefix, url=obj, format=fmt))
    return out


def parse_task(payload: dict[str, Any]) -> ProviderTaskSnapshot:
    data = payload.get("data") or {}
    status = data.get("status") or payload.get("status")
    task_id = data.get("task_id") or payload.get("task_id") or ""
    assets = _collect_urls(data)
    return ProviderTaskSnapshot(
        provider=ProviderId.HI3D,
        task_id=str(task_id),
        status=_normalize_status(status),
        raw_status=status,
        progress=data.get("progress"),
        assets=assets,
        error=None if _normalize_status(status) != CanonicalTaskStatus.FAILED else str(payload.get("msg") or data.get("error") or "Hi3D task failed"),
        metadata={"code": payload.get("code"), "message": payload.get("msg")},
    )


class Hi3DClient:
    def __init__(self, api_key: str, *, transport: Transport | None = None):
        self.api_key = api_key
        self.transport = transport or HttpxTransport(timeout=180.0)

    @property
    def auth(self) -> dict[str, str]:
        return bearer_headers(self.api_key)

    def create_image_file(
        self,
        image_path: str | Path,
        *,
        face_count: int = 5_000_000,
        output_format: str = "glb",
        callback_url: str | None = None,
    ) -> tuple[str, Hi3DSubmissionPlan]:
        image_path = Path(image_path)
        if not image_path.is_file():
            raise FileNotFoundError(image_path)
        plan = high_density_submission_plan(face_count)
        last_error: ProviderExecutionError | None = None
        for target_faces in plan.retry_faces:
            fields = image_task_fields(face_count=target_faces, output_format=output_format, callback_url=callback_url)
            files = {"images": (image_path.name, image_path.read_bytes(), _mime_for(image_path))}
            r = self.transport.request("POST", BASE_URL + "/open-api/v1/submit-task", headers=self.auth, data=fields, files=files)
            body = r.json()
            if r.status_code < 400 and str(body.get("code")) in {"200", "0"} and (body.get("data") or {}).get("task_id"):
                return str(body["data"]["task_id"]), plan
            last_error = ProviderExecutionError(ProviderId.HI3D, body.get("msg", "Hi3D task creation failed"), status_code=r.status_code, payload=body)
            # Only retry the documented 5M -> 2M compatibility ambiguity; other failures should surface immediately.
            if target_faces <= 2_000_000 or str(body.get("code")) not in {"10031002", "400", "422"}:
                raise last_error
        assert last_error is not None
        raise last_error

    def query(self, task_id: str) -> ProviderTaskSnapshot:
        r = self.transport.request("GET", BASE_URL + "/open-api/v1/query-task", headers=self.auth, params={"task_id": task_id})
        body = r.json()
        if r.status_code >= 400 or str(body.get("code")) not in {"200", "0"}:
            raise ProviderExecutionError(ProviderId.HI3D, body.get("msg", "Hi3D task query failed"), status_code=r.status_code, payload=body)
        return parse_task(body)


def _mime_for(path: Path) -> str:
    ext = path.suffix.lower()
    return {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(ext, "application/octet-stream")
