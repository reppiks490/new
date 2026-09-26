from __future__ import annotations

from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field, model_validator


class QualityTier(str, Enum):
    PREVIEW = "preview"
    PRODUCTION = "production"
    COMPAT_2M = "compat_2m"
    HERO_OFFLINE = "hero_offline"


class TextureTier(str, Enum):
    T2K = "2k"
    T4K = "4k"
    T8K = "8k"


class CharacterMode(str, Enum):
    GENERAL = "general"
    ADULT_FICTIONAL = "adult_fictional"


class CharacterSpec(BaseModel):
    prompt: str = Field(min_length=1, max_length=12000)
    mode: CharacterMode = CharacterMode.GENERAL
    fictional: bool = True
    declared_age: int | None = Field(default=None, ge=0, le=150)
    real_person_reference: bool = False
    consent_confirmed: bool = True
    quality_tier: QualityTier = QualityTier.PRODUCTION
    texture_tier: TextureTier = TextureTier.T4K
    udim_tiles: int = Field(default=4, ge=1, le=100)
    requested_triangles: int | None = Field(default=None, ge=1)
    render_engine: Literal["cycles", "unreal", "hybrid"] = "hybrid"
    creature_type: Literal[
        "biped", "quadruped", "hexapod", "octopod", "avian", "serpentine", "aquatic"
    ] = "biped"
    export_formats: list[Literal["usd", "fbx", "gltf", "glb", "obj"]] = ["usd", "glb"]

    @model_validator(mode="after")
    def validate_adult_mode(self):
        if self.mode == CharacterMode.ADULT_FICTIONAL:
            if self.declared_age is None:
                raise ValueError("adult_fictional mode requires declared_age")
            if self.declared_age < 18:
                raise ValueError("adult_fictional mode requires age >= 18")
        return self


class HardwareProfile(BaseModel):
    vram_gb: float = Field(default=12, gt=0, le=512)
    ram_gb: float = Field(default=32, gt=0, le=4096)
    gpu_vendor: Literal["nvidia", "amd", "intel", "apple", "unknown"] = "unknown"
    multi_gpu: bool = False


class PolicyDecision(BaseModel):
    allowed: bool
    reasons: list[str] = []


class GeometryPlan(BaseModel):
    viewport_triangles: int
    interchange_triangles: int
    hero_source_triangles: int
    subdivision_levels: int
    bake_required: bool
    notes: list[str]


class MaterialPlan(BaseModel):
    resolution: int
    udim_tiles: int
    channels: list[str]
    estimated_uncompressed_gib: float
    notes: list[str]


class PipelinePlan(BaseModel):
    policy: PolicyDecision
    geometry: GeometryPlan | None = None
    materials: MaterialPlan | None = None
    stages: list[str] = []
    provider_routes: list[dict] = []
    # Compiled render job (sampling/quality + output resolution), when the
    # caller wants one attached to the plan rather than compiled separately.
    render: dict | None = None
    # Real local pixel analysis of a supplied reference image (dominant
    # palette, contrast, edge density, suggested texture tier) -- see
    # app/pipeline/image_analysis.py. Only present when a reference image
    # was actually supplied to compile_plan.
    image_hints: dict | None = None
