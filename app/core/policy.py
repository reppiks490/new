from __future__ import annotations

import re
from .models import CharacterSpec, CharacterMode, PolicyDecision

_MINOR_TERMS = re.compile(r"\b(child|kid|minor|underage|preteen|pre-teen|teenager|schoolgirl|schoolboy|loli|shota)\b", re.I)
_NONCONSENSUAL_TERMS = re.compile(r"\b(rape|non[- ]?consensual|forced sex|drugged sex|unconscious sex)\b", re.I)
_EXPLICIT_SEX_TERMS = re.compile(r"\b(sex|sexual|nude|naked|porn|xxx|explicit)\b", re.I)


def evaluate_policy(spec: CharacterSpec) -> PolicyDecision:
    reasons: list[str] = []
    text = spec.prompt

    if spec.mode == CharacterMode.ADULT_FICTIONAL:
        if not spec.fictional:
            reasons.append("Explicit/adult mode is restricted to fictional characters.")
        if spec.declared_age is None or spec.declared_age < 18:
            reasons.append("Explicit/adult mode requires a clearly declared adult age of 18+.")
        if _MINOR_TERMS.search(text):
            reasons.append("Sexual content involving minors or minor-appearing characters is not permitted.")
        if _NONCONSENSUAL_TERMS.search(text) or not spec.consent_confirmed:
            reasons.append("Non-consensual sexual content is not permitted.")
        if spec.real_person_reference and _EXPLICIT_SEX_TERMS.search(text):
            reasons.append("Explicit sexual impersonation/deepfakes of real people are not permitted.")

    return PolicyDecision(allowed=not reasons, reasons=reasons)
