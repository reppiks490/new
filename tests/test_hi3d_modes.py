import pytest

from app.providers.hi3d_modes import (
    Hi3DMode,
    multicolor_task_fields,
    portrait_task_fields,
    print_split_task_fields,
    relief_task_fields,
)


def test_portrait_reuses_standard_field_shape_with_portrait_model():
    fields = portrait_task_fields(face_count=1_500_000, output_format="fbx")
    assert fields["mode"] == Hi3DMode.PORTRAIT.value
    assert fields["model"] == "hi3d-portrait"
    assert fields["face"] == "1500000"
    assert fields["format"] == "4"  # fbx per the shared format_map


def test_relief_has_no_face_count_and_restricts_output_format():
    fields = relief_task_fields()
    assert fields["mode"] == Hi3DMode.RELIEF.value
    assert "face" not in fields
    assert fields["format"] == "exr"
    with pytest.raises(ValueError):
        relief_task_fields(output_format="glb")


def test_multicolor_forces_3mf_and_validates_color_count():
    fields = multicolor_task_fields(number_colors=6)
    assert fields["format"] == "6"  # 3mf per the shared format_map
    assert fields["number_color"] == "6"
    with pytest.raises(ValueError):
        multicolor_task_fields(number_colors=1)
    with pytest.raises(ValueError):
        multicolor_task_fields(number_colors=17)


def test_print_split_requires_at_least_two_parts():
    fields = print_split_task_fields(part_count=3, joint_style="snap-fit")
    assert fields["part"] == "3"
    assert fields["joint"] == "snap-fit"
    with pytest.raises(ValueError):
        print_split_task_fields(part_count=1)


def test_all_modes_reuse_high_density_submission_ladder_for_face_count():
    # Portrait/multicolor/print-split all go through image_task_fields, so they
    # inherit the same 5M->2M retry-ladder validation as the standard path.
    fields = portrait_task_fields(face_count=5_000_000)
    assert fields["face"] == "5000000"
    assert fields["resolution"] == "2048master"
