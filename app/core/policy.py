from __future__ import annotations

from .content_filters import FilterCategory, scan_text
from .models import CharacterSpec, CharacterMode, PolicyDecision


def evaluate_policy(spec: CharacterSpec) -> PolicyDecision:
    reasons: list[str] = []

    if spec.mode == CharacterMode.ADULT_FICTIONAL:
        if not spec.fictional:
            reasons.append("Explicit/adult mode is restricted to fictional characters.")
        if spec.declared_age is None or spec.declared_age < 18:
            reasons.append("Explicit/adult mode requires a clearly declared adult age of 18+.")

        result = scan_text(
            spec.prompt,
            real_person_reference=spec.real_person_reference,
            consent_confirmed=spec.consent_confirmed,
            # The whole mode is already an explicit/adult content path, so any
            # minor-referencing term is disqualifying on its own (see
            # scan_text's docstring for why this differs from the general default).
            minor_terms_always_block=True,
        )
        if FilterCategory.MINOR_SEXUAL_CONTENT in result.matched_categories:
            reasons.append("Sexual content involving minors or minor-appearing characters is not permitted.")
        if FilterCategory.NON_CONSENSUAL_SEXUAL_CONTENT in result.matched_categories:
            reasons.append("Non-consensual sexual content is not permitted.")
        if FilterCategory.REAL_PERSON_SEXUAL_CONTENT in result.matched_categories:
            reasons.append("Explicit sexual impersonation/deepfakes of real people are not permitted.")

    return PolicyDecision(allowed=not reasons, reasons=reasons)
