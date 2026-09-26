from __future__ import annotations
from pydantic import BaseModel, Field

class CorrectiveNeed(BaseModel):
    pose_name: str
    joint: str
    angle_degrees: float
    max_edge_stretch: float = 1.0
    relative_volume: float = 1.0
    penetration_count: int = 0
    identity_region: str | None = None

class CorrectiveMorphTarget(BaseModel):
    name: str
    pose_name: str
    joint: str
    trigger_angle_degrees: float
    priority: int
    method: str
    preserve_region: str | None = None
    reasons: list[str] = Field(default_factory=list)

class CorrectivePlan(BaseModel):
    targets: list[CorrectiveMorphTarget]
    driver: str = 'pose_space_rbf'
    notes: list[str] = Field(default_factory=list)


def compile_corrective_plan(needs: list[CorrectiveNeed]) -> CorrectivePlan:
    targets=[]
    for n in needs:
        reasons=[]; priority=0
        if n.max_edge_stretch>1.35: reasons.append('excessive local stretch'); priority+=2
        if not .80<=n.relative_volume<=1.20: reasons.append('volume preservation failure'); priority+=2
        if n.penetration_count: reasons.append('self/body penetration'); priority+=3
        if n.identity_region: reasons.append(f'preserve {n.identity_region} identity region'); priority+=2
        if reasons:
            safe=''.join(c if c.isalnum() else '_' for c in f'{n.joint}_{n.pose_name}').strip('_').lower()
            targets.append(CorrectiveMorphTarget(name=f'corr_{safe}',pose_name=n.pose_name,joint=n.joint,trigger_angle_degrees=n.angle_degrees,priority=priority,method='sculpt_delta_blendshape',preserve_region=n.identity_region,reasons=reasons))
    targets.sort(key=lambda x:(x.priority,abs(x.trigger_angle_degrees)),reverse=True)
    return CorrectivePlan(targets=targets,notes=['Generate correctives non-destructively from a stable neutral topology; validate every corrective against identity and penetration gates.'])
