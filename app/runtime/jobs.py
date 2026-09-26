from __future__ import annotations

import hashlib
import json
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class StageRecord(BaseModel):
    name: str
    status: StageStatus = StageStatus.PENDING
    started_at: float | None = None
    finished_at: float | None = None
    output_paths: list[str] = Field(default_factory=list)
    message: str | None = None


class JobManifest(BaseModel):
    schema_version: str = "character3d-job-v1"
    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: float = Field(default_factory=time.time)
    plan_hash: str
    character: dict[str, Any]
    hardware: dict[str, Any]
    stages: list[StageRecord]
    workspace: str

    def canonical_dict(self) -> dict[str, Any]:
        data = self.model_dump()
        # Volatile identity/timestamps do not participate in reproducibility checks.
        data.pop("job_id", None)
        data.pop("created_at", None)
        for stage in data["stages"]:
            stage["started_at"] = None
            stage["finished_at"] = None
            stage["status"] = StageStatus.PENDING.value
            stage["output_paths"] = []
            stage["message"] = None
        return data

    def reproducibility_hash(self) -> str:
        payload = json.dumps(self.canonical_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        return path


def stable_plan_hash(plan: dict[str, Any]) -> str:
    payload = json.dumps(plan, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
