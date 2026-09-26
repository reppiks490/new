from app.core.models import CharacterSpec, CharacterMode
from app.core.policy import evaluate_policy


def test_adult_fictional_allowed_when_clear_adult():
    s = CharacterSpec(
        prompt="28-year-old fictional adult character, mature anatomy study",
        mode=CharacterMode.ADULT_FICTIONAL,
        fictional=True,
        declared_age=28,
    )
    assert evaluate_policy(s).allowed


def test_minor_sexual_request_blocked():
    s = CharacterSpec(
        prompt="18-year-old fictional schoolgirl nude",
        mode=CharacterMode.ADULT_FICTIONAL,
        fictional=True,
        declared_age=18,
    )
    assert not evaluate_policy(s).allowed


def test_real_person_explicit_deepfake_blocked():
    s = CharacterSpec(
        prompt="explicit nude sexual version of a real celebrity",
        mode=CharacterMode.ADULT_FICTIONAL,
        fictional=False,
        declared_age=30,
        real_person_reference=True,
    )
    assert not evaluate_policy(s).allowed
