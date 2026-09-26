from __future__ import annotations

from pydantic import BaseModel, Field


class SpecializedQAReport(BaseModel):
    subsystem: str
    score: float = Field(ge=0, le=1)
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    passed: bool


class SkinQAInput(BaseModel):
    has_basecolor: bool = True
    has_normal: bool = True
    has_roughness: bool = True
    has_displacement: bool = True
    has_micro_normal: bool = False
    has_sss_profile: bool = False
    displacement_bits: int = 16
    texture_resolution: int = 4096


class EyeQAInput(BaseModel):
    has_cornea_shell: bool = True
    has_sclera: bool = True
    has_iris: bool = True
    has_tearline: bool = False
    cornea_ior: float = 1.376
    iris_depth_mm: float = 0.45


class GroomQAInput(BaseModel):
    strand_count: int = 0
    guide_count: int = 0
    root_coverage: float = Field(default=0, ge=0, le=1)
    mean_segments_per_strand: float = 0
    scalp_binding: bool = False
    has_clump_profile: bool = False


def qa_skin(value: SkinQAInput) -> SpecializedQAReport:
    blockers: list[str] = []
    warnings: list[str] = []
    score = 1.0
    for present, name, penalty in [
        (value.has_basecolor, "base color", 0.20),
        (value.has_normal, "normal", 0.16),
        (value.has_roughness, "roughness", 0.14),
        (value.has_displacement, "displacement", 0.16),
    ]:
        if not present:
            blockers.append(f"Missing {name} map.")
            score -= penalty
    if value.displacement_bits < 16:
        blockers.append("Hero skin displacement must be at least 16-bit.")
        score -= 0.12
    if value.texture_resolution < 4096:
        warnings.append("Skin texture resolution is below the 4K production floor.")
        score -= 0.08
    if not value.has_micro_normal:
        warnings.append("No micro-normal layer; pores/fine wrinkles may collapse at close range.")
        score -= 0.06
    if not value.has_sss_profile:
        warnings.append("No explicit subsurface-scattering profile recorded.")
        score -= 0.08
    score = max(0.0, min(1.0, score))
    return SpecializedQAReport(subsystem="skin", score=round(score,4), blockers=blockers, warnings=warnings, passed=not blockers and score >= 0.75)


def qa_eyes(value: EyeQAInput) -> SpecializedQAReport:
    blockers: list[str] = []
    warnings: list[str] = []
    score = 1.0
    for present, name, penalty in [(value.has_cornea_shell,"cornea shell",0.25),(value.has_sclera,"sclera",0.15),(value.has_iris,"iris",0.20)]:
        if not present:
            blockers.append(f"Missing {name} geometry/material layer.")
            score -= penalty
    if not 1.32 <= value.cornea_ior <= 1.42:
        warnings.append("Cornea IOR is outside the expected human-eye lookdev range.")
        score -= 0.10
    if not 0.20 <= value.iris_depth_mm <= 0.80:
        warnings.append("Iris depth is outside the configured realism envelope.")
        score -= 0.10
    if not value.has_tearline:
        warnings.append("Tearline/wetline layer is absent; close-up realism may suffer.")
        score -= 0.08
    score=max(0.0,min(1.0,score))
    return SpecializedQAReport(subsystem="eyes", score=round(score,4), blockers=blockers, warnings=warnings, passed=not blockers and score >= 0.75)


def qa_groom(value: GroomQAInput) -> SpecializedQAReport:
    blockers: list[str] = []
    warnings: list[str] = []
    score = 1.0
    if value.strand_count < 20_000:
        blockers.append("Groom strand count is below the production minimum of 20k.")
        score -= 0.30
    if value.guide_count < 500:
        warnings.append("Low guide count may reduce controllability during deformation/styling.")
        score -= 0.12
    if value.root_coverage < 0.90:
        warnings.append("Root coverage is below 90%; scalp exposure or bald patches may appear.")
        score -= 0.16
    if value.mean_segments_per_strand < 5:
        warnings.append("Mean strand segmentation is low for smooth hero grooming.")
        score -= 0.12
    if not value.scalp_binding:
        blockers.append("Groom is not recorded as bound to the scalp/deformation surface.")
        score -= 0.22
    if not value.has_clump_profile:
        warnings.append("No clump profile recorded; realism controls are incomplete.")
        score -= 0.08
    score=max(0.0,min(1.0,score))
    return SpecializedQAReport(subsystem="groom", score=round(score,4), blockers=blockers, warnings=warnings, passed=not blockers and score >= 0.70)
