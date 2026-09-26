from __future__ import annotations

from pydantic import BaseModel, Field

from app.release.canonical import CanonicalReleaseManifest


class ArtifactChange(BaseModel):
    key: str
    before_sha256: str
    after_sha256: str
    before_size_bytes: int
    after_size_bytes: int


class EvidenceChange(BaseModel):
    stage: str
    before_mode: str | None = None
    after_mode: str | None = None
    before_success: bool | None = None
    after_success: bool | None = None


class CanonicalReleaseDiff(BaseModel):
    identical: bool
    added_artifacts: list[str] = Field(default_factory=list)
    removed_artifacts: list[str] = Field(default_factory=list)
    changed_artifacts: list[ArtifactChange] = Field(default_factory=list)
    evidence_changes: list[EvidenceChange] = Field(default_factory=list)
    blockers_added: list[str] = Field(default_factory=list)
    blockers_removed: list[str] = Field(default_factory=list)
    releasable_changed: bool = False


def _artifact_key(kind: str, name: str) -> str:
    return f'{kind}:{name}'


def compare_canonical_releases(before: CanonicalReleaseManifest, after: CanonicalReleaseManifest) -> CanonicalReleaseDiff:
    a = {_artifact_key(x.kind, x.name): x for x in before.artifacts}
    b = {_artifact_key(x.kind, x.name): x for x in after.artifacts}
    added = sorted(set(b) - set(a))
    removed = sorted(set(a) - set(b))
    changed = []
    for key in sorted(set(a) & set(b)):
        if (a[key].sha256, a[key].size_bytes) != (b[key].sha256, b[key].size_bytes):
            changed.append(ArtifactChange(
                key=key,
                before_sha256=a[key].sha256,
                after_sha256=b[key].sha256,
                before_size_bytes=a[key].size_bytes,
                after_size_bytes=b[key].size_bytes,
            ))

    before_e = {x.stage: x for x in before.evidence}
    after_e = {x.stage: x for x in after.evidence}
    evidence_changes = []
    for stage in sorted(set(before_e) | set(after_e)):
        left = before_e.get(stage)
        right = after_e.get(stage)
        left_mode = left.mode.value if left else None
        right_mode = right.mode.value if right else None
        left_success = left.success if left else None
        right_success = right.success if right else None
        if (left_mode, left_success) != (right_mode, right_success):
            evidence_changes.append(EvidenceChange(
                stage=stage,
                before_mode=left_mode,
                after_mode=right_mode,
                before_success=left_success,
                after_success=right_success,
            ))

    blockers_added = sorted(set(after.blockers) - set(before.blockers))
    blockers_removed = sorted(set(before.blockers) - set(after.blockers))
    releasable_changed = before.releasable != after.releasable
    identical = not (added or removed or changed or evidence_changes or blockers_added or blockers_removed or releasable_changed)
    return CanonicalReleaseDiff(
        identical=identical,
        added_artifacts=added,
        removed_artifacts=removed,
        changed_artifacts=changed,
        evidence_changes=evidence_changes,
        blockers_added=blockers_added,
        blockers_removed=blockers_removed,
        releasable_changed=releasable_changed,
    )
