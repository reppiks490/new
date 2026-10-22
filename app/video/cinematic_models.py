from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_ID_PATTERN = r'^[a-f0-9]{32}$'
DeliveryResolution = Literal['480p', '720p', '1080p', '1440p', '2160p']
EngineProfile = Literal['low_vram', 'balanced', 'high_quality']


def _dedupe_ids(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


class ContinuityState(BaseModel):
    model_config = ConfigDict(extra='forbid')

    characters: Any | None = None
    wardrobe: Any | None = None
    props: Any | None = None
    location: Any | None = None
    geography: Any | None = None
    lighting: Any | None = None
    time_of_day: Any | None = None
    weather: Any | None = None
    camera_language: Any | None = None
    color_language: Any | None = None
    physical_state: Any | None = None
    story_state: Any | None = None
    immutable_constraints: Any | None = None
    freeform_notes: dict[str, Any] = Field(default_factory=dict)


class ContinuityPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')

    characters: Any | None = None
    wardrobe: Any | None = None
    props: Any | None = None
    location: Any | None = None
    geography: Any | None = None
    lighting: Any | None = None
    time_of_day: Any | None = None
    weather: Any | None = None
    camera_language: Any | None = None
    color_language: Any | None = None
    physical_state: Any | None = None
    story_state: Any | None = None
    immutable_constraints: Any | None = None
    freeform_notes: dict[str, Any] | None = None


def merge_continuity(base: ContinuityState, patch: ContinuityPatch) -> ContinuityState:
    data = deepcopy(base.model_dump(mode='python'))
    patch_data = patch.model_dump(mode='python', exclude_none=True)
    notes_patch = patch_data.pop('freeform_notes', None)
    data.update(patch_data)
    if notes_patch is not None:
        data['freeform_notes'] = {**deepcopy(base.freeform_notes), **deepcopy(notes_patch)}
    return ContinuityState.model_validate(data)


class CinematicShot(BaseModel):
    model_config = ConfigDict(extra='forbid')

    shot_id: str = Field(pattern=_ID_PATTERN)
    ordinal: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=160)
    prompt: str = Field(min_length=1, max_length=20_000)
    negative_prompt: str = Field(default='', max_length=10_000)
    duration_seconds: float = Field(gt=0, le=30.0)
    seed: int = Field(default=0, ge=0, le=2**32 - 1)
    camera_motion: str | None = None
    lens_mm: float | None = Field(default=None, gt=0, le=1000)
    framing: str | None = Field(default=None, max_length=160)
    motion_strength: float | None = Field(default=None, ge=0.0, le=1.0)
    reference_image_ids: list[str] = Field(default_factory=list)
    continuity_patch: ContinuityPatch = Field(default_factory=ContinuityPatch)
    transition_in: str | None = Field(default=None, max_length=160)
    transition_out: str | None = Field(default=None, max_length=160)
    engine_profile: EngineProfile = 'balanced'
    latest_job_id: str | None = Field(default=None, pattern=_ID_PATTERN)
    latest_asset_url: str | None = None
    latest_rendered_project_revision: int | None = Field(default=None, ge=1)

    @field_validator('reference_image_ids')
    @classmethod
    def dedupe_reference_ids(cls, values: list[str]) -> list[str]:
        for value in values:
            if len(value) != 32 or any(ch not in '0123456789abcdef' for ch in value):
                raise ValueError('reference image ids must be lowercase 32-character hex values')
        return _dedupe_ids(values)


class CinematicScene(BaseModel):
    model_config = ConfigDict(extra='forbid')

    scene_id: str = Field(pattern=_ID_PATTERN)
    ordinal: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=160)
    synopsis: str = Field(default='', max_length=4000)
    source_text: str = Field(default='', max_length=100_000)
    target_duration_seconds: float = Field(gt=0, le=28_800)
    reference_image_ids: list[str] = Field(default_factory=list)
    continuity_patch: ContinuityPatch = Field(default_factory=ContinuityPatch)
    shots: list[CinematicShot] = Field(default_factory=list)

    @field_validator('reference_image_ids')
    @classmethod
    def dedupe_reference_ids(cls, values: list[str]) -> list[str]:
        for value in values:
            if len(value) != 32 or any(ch not in '0123456789abcdef' for ch in value):
                raise ValueError('reference image ids must be lowercase 32-character hex values')
        return _dedupe_ids(values)


class CinematicProject(BaseModel):
    model_config = ConfigDict(extra='forbid')

    revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=160)
    master_prompt: str = Field(min_length=1, max_length=100_000)
    target_duration_seconds: float = Field(ge=10, le=28_800)
    delivery_fps: int = Field(ge=1, le=120)
    delivery_resolution: DeliveryResolution
    aspect_ratio: str = Field(min_length=3, max_length=16)
    continuity_bible: ContinuityState = Field(default_factory=ContinuityState)
    reference_image_ids: list[str] = Field(default_factory=list)
    scenes: list[CinematicScene] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @field_validator('master_prompt')
    @classmethod
    def reject_blank_master_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('master_prompt cannot be blank')
        return value

    @field_validator('reference_image_ids')
    @classmethod
    def dedupe_reference_ids(cls, values: list[str]) -> list[str]:
        for value in values:
            if len(value) != 32 or any(ch not in '0123456789abcdef' for ch in value):
                raise ValueError('reference image ids must be lowercase 32-character hex values')
        return _dedupe_ids(values)

    @model_validator(mode='after')
    def reject_duplicate_ids(self) -> 'CinematicProject':
        scene_ids = [scene.scene_id for scene in self.scenes]
        if len(scene_ids) != len(set(scene_ids)):
            raise ValueError('duplicate scene_id values are not allowed')
        shot_ids = [shot.shot_id for scene in self.scenes for shot in scene.shots]
        if len(shot_ids) != len(set(shot_ids)):
            raise ValueError('duplicate shot_id values are not allowed')
        return self
