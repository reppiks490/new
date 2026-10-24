"""Read-only QA36 audit of implicit cinematic continuity resets.

This helper follows the existing per-shot scoped continuity resolution exactly.
It does not decide whether persistence is desirable or change render plans.
The returned report contains IDs and field names only, never private values.
"""

from __future__ import annotations

from app.video.cinematic_models import CinematicProject, merge_continuity


def audit_implicit_continuity_resets(project: CinematicProject) -> dict:
    """Identify field changes caused by scope fallback, not explicit new patches.

    A shot patch currently applies to that shot alone. Scene patches currently
    apply to their own scenes alone. Reversions can therefore be intentional;
    every finding is advisory and requires editorial review.
    """
    previous: dict | None = None
    findings: list[dict] = []

    for scene_index, scene in enumerate(project.scenes):
        scene_state = merge_continuity(project.continuity_bible, scene.continuity_patch)
        scene_explicit = set(
            scene.continuity_patch.model_dump(mode='python', exclude_none=True)
        )
        for shot_index, shot in enumerate(scene.shots):
            current_state = merge_continuity(scene_state, shot.continuity_patch)
            current = current_state.model_dump(mode='python')
            explicit = set(
                shot.continuity_patch.model_dump(mode='python', exclude_none=True)
            )
            if shot_index == 0:
                explicit.update(scene_explicit)

            if previous is not None:
                changed_without_patch = sorted(
                    field
                    for field in current
                    if previous[field] != current[field] and field not in explicit
                )
                if changed_without_patch:
                    findings.append({
                        'scene_id': scene.scene_id,
                        'shot_id': shot.shot_id,
                        'scope': 'scene_boundary' if shot_index == 0 else 'shot_boundary',
                        'field_names': changed_without_patch,
                    })
            previous = current

    return {
        'project_id': project.id,
        'project_revision': project.revision,
        'potential_reset_count': len(findings),
        'potential_resets': findings,
        'advisory_only': True,
    }
