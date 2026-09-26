from __future__ import annotations

import re
from enum import Enum
from pydantic import BaseModel, Field

# Single source of truth for prompt-text safety patterns. Previously these regexes
# lived only inside app/core/policy.py, scoped to CharacterSpec's adult-fictional
# gate — meaning any other prompt surface added later (scene/world prompts, prop
# prompts) got NO filtering at all. Centralizing here means every prompt-accepting
# spec in this project runs through the same filter, not an ad hoc copy.


class FilterCategory(str, Enum):
    MINOR_SEXUAL_CONTENT = "minor_sexual_content"
    NON_CONSENSUAL_SEXUAL_CONTENT = "non_consensual_sexual_content"
    REAL_PERSON_SEXUAL_CONTENT = "real_person_sexual_content"
    EXPLICIT_SEXUAL_CONTENT = "explicit_sexual_content"  # generic NSFW signal; not inherently blocking on its own


# Categories that are unconditionally disqualifying wherever they're detected,
# independent of mode/tier/consent flags. Nothing overrides these.
HARD_BLOCK_CATEGORIES = frozenset({
    FilterCategory.MINOR_SEXUAL_CONTENT,
    FilterCategory.NON_CONSENSUAL_SEXUAL_CONTENT,
})

MINOR_TERMS = re.compile(
    r"\b(child|kid|minor|underage|preteen|pre-teen|teenager|schoolgirl|schoolboy|loli|shota)\b", re.I
)
NONCONSENSUAL_TERMS = re.compile(
    r"\b(rape|non[- ]?consensual|forced sex|drugged sex|unconscious sex)\b", re.I
)
EXPLICIT_SEX_TERMS = re.compile(
    r"\b(sex|sexual|nude|naked|porn|xxx|explicit|nsfw)\b", re.I
)


class ContentFilterResult(BaseModel):
    matched_categories: set[FilterCategory] = Field(default_factory=set)
    # True if ANY explicit/adult-oriented language was detected, regardless of
    # whether it's actually blocked. Useful for tagging/routing (e.g. a scene
    # marked nsfw_signal can be excluded from a "family-friendly" export preset)
    # without itself being a policy violation.
    nsfw_signal: bool = False

    @property
    def hard_blocked(self) -> bool:
        return bool(self.matched_categories & HARD_BLOCK_CATEGORIES)


def scan_text(
    text: str,
    *,
    real_person_reference: bool = False,
    consent_confirmed: bool = True,
    minor_terms_always_block: bool = False,
) -> ContentFilterResult:
    """General-purpose prompt-text safety scan.

    minor_terms_always_block=True reproduces the stricter historical behavior of
    CharacterSpec's ADULT_FICTIONAL gate: since that entire mode is already an
    explicit/adult content path, ANY minor-referencing term is disqualifying on
    its own, regardless of whether it co-occurs with explicit sexual language in
    the same string. For general prompt surfaces (scenes, props, non-adult-mode
    characters) that would over-block ordinary content like "a schoolyard with
    children playing", so the default instead requires co-occurrence with
    explicit sexual language before flagging MINOR_SEXUAL_CONTENT.
    """
    categories: set[FilterCategory] = set()
    nsfw_signal = bool(EXPLICIT_SEX_TERMS.search(text))
    has_minor_term = bool(MINOR_TERMS.search(text))

    if has_minor_term and (minor_terms_always_block or nsfw_signal):
        categories.add(FilterCategory.MINOR_SEXUAL_CONTENT)
    if NONCONSENSUAL_TERMS.search(text) or (nsfw_signal and not consent_confirmed):
        categories.add(FilterCategory.NON_CONSENSUAL_SEXUAL_CONTENT)
    if real_person_reference and nsfw_signal:
        categories.add(FilterCategory.REAL_PERSON_SEXUAL_CONTENT)
    if nsfw_signal:
        categories.add(FilterCategory.EXPLICIT_SEXUAL_CONTENT)

    return ContentFilterResult(matched_categories=categories, nsfw_signal=nsfw_signal)
