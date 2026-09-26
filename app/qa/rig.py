from __future__ import annotations
from pydantic import BaseModel, Field

class VertexWeights(BaseModel):
    influences: dict[str,float]

class RigWeightQAInput(BaseModel):
    vertices: list[VertexWeights]
    known_bones: set[str] = Field(default_factory=set)
    max_influences: int = 4
    sum_tolerance: float = 0.02

class RigWeightQAReport(BaseModel):
    vertex_count: int
    invalid_sum_count: int
    excessive_influence_count: int
    zero_weight_count: int
    negative_weight_count: int
    unknown_bone_count: int
    passed: bool
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def qa_skin_weights(value: RigWeightQAInput) -> RigWeightQAReport:
    invalid=excessive=zero=negative=unknown=0
    for vw in value.vertices:
        vals=list(vw.influences.values()); total=sum(vals)
        if not vals or abs(total)<=1e-12: zero+=1
        if vals and abs(total-1.0)>value.sum_tolerance: invalid+=1
        if sum(1 for x in vals if x>1e-8)>value.max_influences: excessive+=1
        if any(x<0 for x in vals): negative+=1
        if value.known_bones: unknown += sum(1 for b in vw.influences if b not in value.known_bones)
    blockers=[]; warnings=[]
    if zero: blockers.append(f'{zero} vertices have zero total skin weight.')
    if negative: blockers.append(f'{negative} vertices contain negative skin weights.')
    if invalid: blockers.append(f'{invalid} vertices have weights outside the sum tolerance.')
    if excessive: warnings.append(f'{excessive} vertices exceed {value.max_influences} active influences.')
    if unknown: blockers.append(f'{unknown} influences reference unknown bones.')
    return RigWeightQAReport(vertex_count=len(value.vertices),invalid_sum_count=invalid,excessive_influence_count=excessive,zero_weight_count=zero,negative_weight_count=negative,unknown_bone_count=unknown,passed=not blockers,blockers=blockers,warnings=warnings)

class PoseDeformationSample(BaseModel):
    pose_name: str
    mean_edge_stretch: float = Field(gt=0)
    max_edge_stretch: float = Field(gt=0)
    relative_volume: float = Field(gt=0)
    penetration_count: int = Field(default=0,ge=0)

class PoseDeformationReport(BaseModel):
    pose_count: int
    failed_poses: list[str]
    passed: bool
    blockers: list[str] = Field(default_factory=list)


def qa_pose_deformation(samples: list[PoseDeformationSample], *, max_stretch: float=1.35, min_volume: float=0.80, max_volume: float=1.20) -> PoseDeformationReport:
    failed=[]; blockers=[]
    for s in samples:
        reasons=[]
        if s.max_edge_stretch>max_stretch: reasons.append(f'max stretch {s.max_edge_stretch:.3f}')
        if not min_volume<=s.relative_volume<=max_volume: reasons.append(f'relative volume {s.relative_volume:.3f}')
        if s.penetration_count>0: reasons.append(f'{s.penetration_count} penetrations')
        if reasons:
            failed.append(s.pose_name); blockers.append(f'{s.pose_name}: '+', '.join(reasons))
    return PoseDeformationReport(pose_count=len(samples),failed_poses=failed,passed=not failed,blockers=blockers)
