import pytest
from pydantic import ValidationError

from app.image.models import ImageEditRequest

VALID_ID = "0123456789abcdef0123456789abcdef"


def test_image_edit_request_normalizes_prompt_and_defaults_seed():
    req = ImageEditRequest(image_id=VALID_ID, prompt="  make the jacket red  ")
    assert req.prompt == "make the jacket red"
    assert req.seed == 0


def test_image_edit_request_rejects_invalid_id_empty_prompt_and_extra_fields():
    with pytest.raises(ValidationError):
        ImageEditRequest(image_id="bad", prompt="edit")
    with pytest.raises(ValidationError):
        ImageEditRequest(image_id=VALID_ID, prompt="   ")
    with pytest.raises(ValidationError):
        ImageEditRequest(image_id=VALID_ID, prompt="edit", unexpected=True)
