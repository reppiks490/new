from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class ProviderId(str, Enum):
    TRIPO = "tripo"
    MESHY = "meshy"
    HI3D = "hi3d"


class Capability(str, Enum):
    TEXT_TO_3D = "text_to_3d"
    IMAGE_TO_3D = "image_to_3d"
    MULTIVIEW_TO_3D = "multiview_to_3d"
    PBR = "pbr"
    TEXTURE_8K = "texture_8k"
    GEOMETRY_4K_PASS = "geometry_4k_pass"
    HIGH_DENSITY_2M = "high_density_2m"
    HIGH_DENSITY_5M = "high_density_5m"
    SMART_TOPOLOGY = "smart_topology"
    QUAD_OUTPUT = "quad_output"
    SEGMENTATION = "segmentation"
    RETEXTURE = "retexture"
    REMESH = "remesh"
    UV_UNWRAP = "uv_unwrap"
    RIGGING = "rigging"
    ANIMATION = "animation"
    PORTRAIT_SPECIALIST = "portrait_specialist"
    PRINT_SPLIT = "print_split"
    MULTICOLOR_3D = "multicolor_3d"
    RELIEF = "relief"
    PRINT_3MF = "print_3mf"
    USDZ = "usdz"


class ProviderProfile(BaseModel):
    provider: ProviderId
    capabilities: set[Capability]
    advertised_max_faces: int | None = None
    conservative_submit_max_faces: int | None = None
    max_texture_resolution: int | None = None
    geometry_resolution_label: str | None = None
    notes: list[str] = []
    metadata: dict[str, Any] = {}


class ProviderRoute(BaseModel):
    stage: str
    selected: ProviderId
    alternatives: list[ProviderId] = []
    reasons: list[str] = []
    required_capabilities: set[Capability] = set()
    warnings: list[str] = []


class ProviderRoutingPlan(BaseModel):
    routes: list[ProviderRoute] = []
    strategy: str = "best_capability_per_stage"
    notes: list[str] = []
