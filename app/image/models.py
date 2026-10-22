from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ImageEditRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    image_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    prompt: str = Field(min_length=1, max_length=2000)
    seed: int = Field(default=0, ge=0, le=2**32 - 1)

    @field_validator('prompt')
    @classmethod
    def normalize_prompt(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError('Prompt cannot be empty')
        return value


class ImageEngineCapabilities(BaseModel):
    name: str
    available: bool = False
    supports_editing: bool = True
    precision: str | None = None
    min_vram_mb: int | None = None
    detail: str = ''
