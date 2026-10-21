from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


EngineProfile = Literal['low_vram', 'balanced', 'high_quality']
ResolutionPreset = Literal['480p', '720p', '1080p']
CameraMotionPreset = Literal[
    'static',
    'pan_left',
    'pan_right',
    'tilt_up',
    'tilt_down',
    'zoom_in',
    'zoom_out',
    'orbit',
]


class VideoGenerationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    image_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    prompt: str = Field(min_length=1, max_length=2000)
    engine_profile: EngineProfile = 'balanced'
    seed: int = Field(default=0, ge=0, le=2**32 - 1)
    duration_seconds: float = Field(default=5.0, ge=1.0, le=30.0)
    fps: int = Field(default=24, ge=1, le=60)
    resolution: ResolutionPreset = '720p'
    motion_strength: float | None = Field(default=None, ge=0.0, le=1.0)
    camera_motion: CameraMotionPreset | None = None

    @field_validator('prompt')
    @classmethod
    def normalize_prompt(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError('Prompt cannot be empty')
        return value


class PrivacyPreferences(BaseModel):
    model_config = ConfigDict(extra='forbid')
    privacy_mode: bool = True
    mask_prompts: bool = True
    blur_media: bool = True
    quick_hide: bool = True
    idle_lock_seconds: int = Field(default=30, ge=0, le=3600)
    require_unlock_on_resume: bool = True
    neutral_project_names: bool = True


class EngineCapabilities(BaseModel):
    name: str
    available: bool = False
    profiles: list[EngineProfile] = Field(default_factory=list)
    supported_resolutions: list[ResolutionPreset] = Field(default_factory=list)
    min_duration_seconds: float = 1.0
    max_duration_seconds: float = 30.0
    supported_fps: list[int] = Field(default_factory=list)
    supports_motion_strength: bool = False
    camera_motion_presets: list[CameraMotionPreset] = Field(default_factory=list)
    detail: str = ''


class VideoRuntimeReport(BaseModel):
    enabled: bool = True
    available: bool = False
    gpu_name: str | None = None
    vram_total_mb: int | None = None
    vram_free_mb: int | None = None
    cuda_available: bool = False
    ffmpeg_available: bool = False
    recommended_profile: EngineProfile | None = None
    engines: list[EngineCapabilities] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
