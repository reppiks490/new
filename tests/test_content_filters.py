from app.core.content_filters import FilterCategory, scan_text


def test_plain_prompt_has_no_signal():
    result = scan_text("a friendly fictional adventurer in a forest")
    assert not result.nsfw_signal
    assert not result.matched_categories
    assert not result.hard_blocked


def test_nsfw_signal_set_by_explicit_terms_without_blocking_by_default():
    result = scan_text("a nude fictional adult figure study")
    assert result.nsfw_signal
    assert FilterCategory.EXPLICIT_SEXUAL_CONTENT in result.matched_categories
    assert not result.hard_blocked


def test_minor_term_alone_is_not_blocked_by_default():
    # "children playing in a park" must not trip a sexual-content filter just
    # because it mentions minors with no sexual language at all.
    result = scan_text("a schoolyard with children playing")
    assert not result.hard_blocked
    assert FilterCategory.MINOR_SEXUAL_CONTENT not in result.matched_categories


def test_minor_plus_explicit_terms_is_hard_blocked_by_default():
    result = scan_text("a nude schoolgirl")
    assert result.hard_blocked
    assert FilterCategory.MINOR_SEXUAL_CONTENT in result.matched_categories


def test_minor_terms_always_block_flag_blocks_without_explicit_cooccurrence():
    result = scan_text("a teenager in a fictional setting", minor_terms_always_block=True)
    assert result.hard_blocked
    assert FilterCategory.MINOR_SEXUAL_CONTENT in result.matched_categories


def test_nonconsensual_terms_hard_blocked():
    result = scan_text("a forced sex scenario")
    assert result.hard_blocked
    assert FilterCategory.NON_CONSENSUAL_SEXUAL_CONTENT in result.matched_categories


def test_unconfirmed_consent_with_explicit_content_is_hard_blocked():
    result = scan_text("explicit nude scene", consent_confirmed=False)
    assert result.hard_blocked


def test_real_person_reference_with_explicit_terms_flagged():
    result = scan_text("explicit nude version of a real person", real_person_reference=True)
    assert FilterCategory.REAL_PERSON_SEXUAL_CONTENT in result.matched_categories
    # Real-person sexual content is a serious violation but is not in
    # HARD_BLOCK_CATEGORIES here because CharacterSpec's own policy layer
    # additionally gates it via the fictional=False check; scan_text still
    # surfaces the category so any caller can choose to block on it.
    assert FilterCategory.REAL_PERSON_SEXUAL_CONTENT in result.matched_categories
