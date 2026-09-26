from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.providers.models import ProviderId


class AssetProvenance(BaseModel):
    provider: ProviderId
    task_id: str
    provider_asset_url: str
    local_path: str
    sha256: str
    size_bytes: int
    format: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def save_asset_provenance(record: AssetProvenance, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record.model_dump(mode="json"), indent=2, sort_keys=True), encoding="utf-8")
    return path
