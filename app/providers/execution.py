from __future__ import annotations

import hashlib
import json
import os
import time
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Protocol
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from app.providers.models import ProviderId


class CanonicalTaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class RemoteAsset(BaseModel):
    kind: str
    url: str
    format: str | None = None
    expires_at: float | None = None
    sha256: str | None = None
    local_path: str | None = None
    size_bytes: int | None = None


class ProviderTaskSnapshot(BaseModel):
    provider: ProviderId
    task_id: str
    status: CanonicalTaskStatus
    progress: int | None = Field(default=None, ge=0, le=100)
    assets: list[RemoteAsset] = Field(default_factory=list)
    raw_status: str | None = None
    credits_consumed: float | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def terminal(self) -> bool:
        return self.status in {
            CanonicalTaskStatus.SUCCEEDED,
            CanonicalTaskStatus.FAILED,
            CanonicalTaskStatus.CANCELLED,
        }


class ProviderExecutionError(RuntimeError):
    def __init__(self, provider: ProviderId, message: str, *, status_code: int | None = None, payload: Any = None):
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.payload = payload


class Transport(Protocol):
    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response: ...


class HttpxTransport:
    def __init__(self, *, timeout: float = 60.0):
        self.timeout = timeout
        self.client = httpx.Client(timeout=timeout, follow_redirects=True)

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        return self.client.request(method, url, **kwargs)

    def close(self) -> None:
        self.client.close()


def bearer_headers(api_key: str) -> dict[str, str]:
    if not api_key.strip():
        raise ValueError("API key is empty")
    return {"Authorization": f"Bearer {api_key}"}


def api_key_from_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def require_https(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("Only absolute HTTPS asset URLs are accepted")


def host_is_allowed(url: str, allowed_hosts: Iterable[str]) -> bool:
    require_https(url)
    host = (urlparse(url).hostname or "").lower()
    for allowed in allowed_hosts:
        allowed = allowed.lower().lstrip(".")
        if host == allowed or host.endswith("." + allowed):
            return True
    return False


def _content_length(response: httpx.Response) -> int | None:
    value = response.headers.get("content-length")
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _validate_response_target(response: httpx.Response, allowed_hosts: Iterable[str]) -> None:
    # httpx follows redirects for the production transport. Re-check the final URL so a trusted
    # provider URL cannot redirect the downloader to an untrusted host.
    final_url = str(response.url) if response.url else ""
    if final_url and not host_is_allowed(final_url, allowed_hosts):
        raise ValueError(f"Asset redirect landed on an untrusted host: {urlparse(final_url).hostname}")


def download_verified_asset(
    url: str,
    destination: str | Path,
    *,
    allowed_hosts: Iterable[str],
    max_bytes: int = 2_000_000_000,
    expected_sha256: str | None = None,
    transport: Transport | None = None,
    chunk_size: int = 1024 * 1024,
) -> RemoteAsset:
    if not host_is_allowed(url, allowed_hosts):
        raise ValueError(f"Asset host is not trusted for provider download: {urlparse(url).hostname}")
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".part")
    tmp.unlink(missing_ok=True)
    digest = hashlib.sha256()
    size = 0

    def consume(response: httpx.Response) -> RemoteAsset:
        nonlocal size
        if response.status_code >= 400:
            raise RuntimeError(f"Asset download failed with HTTP {response.status_code}")
        _validate_response_target(response, allowed_hosts)
        declared = _content_length(response)
        if declared is not None and declared > max_bytes:
            raise ValueError(f"Remote asset exceeds size cap ({declared} > {max_bytes})")
        with tmp.open("wb") as f:
            for chunk in response.iter_bytes(chunk_size=chunk_size):
                if not chunk:
                    continue
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError(f"Remote asset exceeds size cap ({size} > {max_bytes})")
                digest.update(chunk)
                f.write(chunk)
        sha = digest.hexdigest()
        if expected_sha256 and sha.lower() != expected_sha256.lower():
            raise ValueError("Downloaded asset SHA-256 mismatch")
        tmp.replace(destination)
        return RemoteAsset(
            kind="download",
            url=url,
            format=destination.suffix.lstrip(".").lower() or None,
            sha256=sha,
            local_path=str(destination),
            size_bytes=size,
        )

    try:
        if transport is None:
            with httpx.stream("GET", url, timeout=180.0, follow_redirects=True) as response:
                return consume(response)
        response = transport.request("GET", url)
        return consume(response)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def write_provenance_receipt(snapshot: ProviderTaskSnapshot, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "character3d-provider-receipt-v1",
        "captured_at": time.time(),
        "snapshot": snapshot.model_dump(mode="json"),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path
