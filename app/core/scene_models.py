from __future__ import annotations

import math
from enum import Enum
from pydantic import BaseModel, Field, model_validator


class AssetKind(str, Enum):
    CHARACTER = "character"
    PROP = "prop"
    ENVIRONMENT = "environment"
    LIGHT = "light"
    CAMERA = "camera"


class SceneScale(str, Enum):
    ROOM = "room"
    BUILDING = "building"
    DISTRICT = "district"
    OPEN_WORLD = "open_world"


class Transform(BaseModel):
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation_euler_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)

    @model_validator(mode="after")
    def validate_finite_nonzero_scale(self):
        for group in (self.position, self.rotation_euler_deg, self.scale):
            if not all(math.isfinite(v) for v in group):
                raise ValueError("transform values must be finite")
        if any(abs(s) < 1e-9 for s in self.scale):
            raise ValueError("scale components must be non-zero")
        return self


class SceneAssetInstance(BaseModel):
    instance_id: str = Field(min_length=1, max_length=200)
    asset_kind: AssetKind
    # SHA-256 of the canonical, already-QA'd/policy'd promoted asset this instance
    # places into the scene. Scene assembly composes vetted content-addressed
    # assets; it does not re-run character generation or policy gating — that
    # already happened upstream, per-asset (see app/core/policy.py). This keeps
    # scene assembly a placement/composition concern, not a new generation surface.
    asset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    transform: Transform = Field(default_factory=Transform)
    display_name: str | None = None
    # Optional pre-computed geometry footprint, so scene-level budgeting doesn't
    # need to re-inspect every referenced mesh just to estimate total triangle load.
    viewport_triangles: int | None = Field(default=None, ge=0)
    hero_source_triangles: int | None = Field(default=None, ge=0)
    # Optional bounding-sphere radius (meters) for cheap placement/overlap QA
    # without loading geometry.
    bounding_radius_m: float | None = Field(default=None, ge=0)


class EnvironmentLighting(BaseModel):
    hdri_reference_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    sun_intensity: float = Field(default=1.0, ge=0)
    ambient_occlusion: bool = True


class SceneSpec(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # Free-text environment/world description (used to drive local or
    # provider-assisted environment/HDRI/set-dressing generation). A scene prompt
    # is not a character generation prompt and is not routed through
    # app.core.policy's adult-fictional character gate.
    prompt: str = Field(default="", max_length=12000)
    scale: SceneScale = SceneScale.ROOM
    assets: list[SceneAssetInstance] = Field(default_factory=list)
    lighting: EnvironmentLighting = Field(default_factory=EnvironmentLighting)
    bounds_meters: tuple[float, float, float] = (10.0, 10.0, 10.0)

    @model_validator(mode="after")
    def validate_unique_instance_ids(self):
        ids = [a.instance_id for a in self.assets]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate scene instance_id(s): {dupes}")
        return self
