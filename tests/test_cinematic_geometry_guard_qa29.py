"""Pure local geometry-guard controls; no FFmpeg, GPU or model inference."""
import pytest

from app.video.cinematic_geometry_guard_qa29 import validate_master_geometry


@pytest.mark.parametrize("width,height,ratio", [
    (854, 480, "16:9"),
    (3840, 2160, "16:9"),
    (5162, 2160, "239:100"),
    (1216, 2160, "9:16"),
])
def test_standard_and_cinematic_geometry_accepted(width, height, ratio):
    assert validate_master_geometry(width, height, ratio) == (width, height)


@pytest.mark.parametrize("width,height,ratio", [
    (479999999999520, 480, "999999999999:1"),
    (2, 480, "1:999999999999"),
    (8194, 2160, "4:1"),
    (854, 480, "16:0"),
    (853, 480, "16:9"),
])
def test_extreme_distorted_and_invalid_geometry_rejected(width, height, ratio):
    with pytest.raises(ValueError):
        validate_master_geometry(width, height, ratio)


def test_errors_do_not_repeat_private_ratio_or_prompt():
    private_value = "999999999999:1"
    with pytest.raises(ValueError) as caught:
        validate_master_geometry(479999999999520, 480, private_value)
    assert private_value not in str(caught.value)
