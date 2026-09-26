from __future__ import annotations

from .content_filters import FilterCategory, scan_text
from .models import PolicyDecision
from .scene_models import SceneSpec


def evaluate_scene_policy(scene: SceneSpec) -> PolicyDecision:
    """Content-safety gate for scene/world prompts.

    Scene composition (app/core/scene_models.py) references already-generated,
    already-policy'd canonical assets by content hash — it doesn't itself
    generate character content, so it was previously *unfiltered*: a scene's
    free-text `prompt` (environment/world description) and each instance's
    `display_name` had no content-safety check at all. This closes that gap
    using the same shared filter as CharacterSpec, without inheriting
    CharacterSpec's adult-mode-specific machinery (declared_age, fictional,
    consent_confirmed) which doesn't apply to an environment description.
    """
    reasons: list[str] = []
    texts = [scene.prompt] + [a.display_name for a in scene.assets if a.display_name]

    for text in texts:
        if not text:
            continue
        result = scan_text(text)
        if FilterCategory.MINOR_SEXUAL_CONTENT in result.matched_categories:
            reasons.append(
                "Sexual content involving minors or minor-appearing characters is not permitted."
            )
        if FilterCategory.NON_CONSENSUAL_SEXUAL_CONTENT in result.matched_categories:
            reasons.append("Non-consensual sexual content is not permitted.")

    # De-duplicate while preserving order (multiple asset display_names could
    # trip the same rule).
    seen: set[str] = set()
    unique_reasons = [r for r in reasons if not (r in seen or seen.add(r))]
    return PolicyDecision(allowed=not unique_reasons, reasons=unique_reasons)
