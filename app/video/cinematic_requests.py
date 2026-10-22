from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CompileProjectRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: int = Field(ge=1)
    preferred_shot_seconds: float = Field(default=10.0, gt=0, le=30.0)
    engine_max_duration_seconds: float = Field(default=10.0, gt=0, le=30.0)
    engine_name: str | None = Field(default=None, min_length=1, max_length=160)


class ShotRenderRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: int = Field(ge=1)
    engine_name: str | None = Field(default=None, min_length=1, max_length=160)
