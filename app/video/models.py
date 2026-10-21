from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


EngineProfile = Literal['auto', 'low_vram', 'balanced', 'high_quality']
ResolutionPreset = Literal['480p', '720p', '1080p']


class VideoGenerationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    image_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    prompt: str = Field(min_length=1, max_length=12_000)
    engine_profile: EngineProfile = 'auto'
    seed: int = Field(default=0, ge=0, le=(2**63 - 1))
    duration_seconds: int = Field(default=4, ge=1, le=12)
    fps: int = Field(default=24, ge=1, le=60)
    resolution: ResolutionPreset = '720p'
    motion_strength: float | None = Field(default=None, ge=0.0, le=1.0)
    camera_motion: str | None = Field(default=None, max_length=64)

    @field_validator('prompt')
    @classmethod
    def prompt_must_have_visible_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('Prompt must contain visible text')
        return value


class PrivacyPreferences(BaseModel):
    model_config = ConfigDict(extra='forbid')

    privacy_mode: bool = True
    mask_prompts: bool = True
    blur_media: bool = True
    quick_hide: bool = True
    idle_lock_seconds: int = Field(default=30, ge=5, le=3600)
    require_unlock_on_resume: bool = True
    neutral_project_names: bool = True


class EngineCapabilities(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: str
    available: bool = False
    profiles: list[EngineProfile] = Field(default_factory=list)
    resolutions: list[ResolutionPreset] = Field(default_factory=list)
    min_duration_seconds: int = 1
    max_duration_seconds: int = 12
    min_fps: int = 1
    max_fps: int = 60
    supports_motion_strength: bool = False
    supports_camera_motion: bool = False
    detail: str = ''


class VideoRuntimeReport(BaseModel):
    model_config = ConfigDict(extra='forbid')

    enabled: bool = True
    available: bool = False
    gpu_name: str | None = None
    vram_total_mb: int | None = None
    vram_free_mb: int | None = None
    cuda_available: bool = False
    torch_available: bool = False
    ffmpeg_available: bool = False
    recommended_profile: EngineProfile | None = None
    engines: list[EngineCapabilities] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class VideoJobPublic(BaseModel):
    model_config = ConfigDict(extra='allow')

    id: str
    status: str
    stage: str
    progress: int = Field(default=0, ge=0, le=100)
