"""Local source-asset QA: no GPU, network, FFmpeg or real user media."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from PIL import Image
import pytest

from app.video.cinematic_models import CinematicProject, CinematicScene, CinematicShot
from app.video.cinematic_reference_preflight import audit_reference_files

A = "a" * 32
B = "b" * 32
C = "c" * 32


def _project(*, refs=None, scene_refs=None, shot_refs=None, shots=2):
    now = datetime.now(timezone.utc)
    clips = [
        CinematicShot(
            shot_id=f"{i+100:032x}",
            ordinal=i+1,
            title="SECRET SHOT",
            prompt="NEVER INCLUDE SECRET PROMPT IN FINDINGS",
            duration_seconds=5,
            reference_image_ids=shot_refs or [],
        )
        for i in range(shots)
    ]
    return CinematicProject(
        id="f" * 32,
        revision=9,
        title="PRIVATE PROJECT TITLE",
        master_prompt="SECRET MASTER SCREENPLAY",
        target_duration_seconds=max(10, shots * 5),
        delivery_fps=24,
        delivery_resolution="1080p",
        aspect_ratio="16:9",
        reference_image_ids=refs or [],
        scenes=[
            CinematicScene(
                scene_id="1" * 32,
                ordinal=1,
                title="PRIVATE SCENE TITLE",
                target_duration_seconds=max(1, shots * 5),
                reference_image_ids=scene_refs or [],
                shots=clips,
            ),
        ],
        created_at=now,
        updated_at=now,
    )


def _png(workspace: Path, identifier: str, *, width=3, height=3):
    directory = workspace / "video-assets"
    directory.mkdir(exist_ok=True, parents=True)
    path = directory / f"{identifier}.png"
    Image.new("RGB", (width, height), (33, 12, 77)).save(path, format="PNG")
    return path


def _codes(result):
    return [finding.code for finding in result.findings]


def test_real_png_passes_and_deduplicates_across_many_shots(tmp_path):
    _png(tmp_path, A)
    project = _project(refs=[A], scene_refs=[A], shot_refs=[A], shots=260)
    report = audit_reference_files(project, workspace=tmp_path)
    assert report.references_ready
    assert report.shot_count == report.shots_with_valid_references == 260
    assert report.unique_references == report.valid_unique_references == 1
    assert not report.findings


def test_missing_reference_is_attributed_to_every_impacted_shot(tmp_path):
    _png(tmp_path, A)
    project = _project(refs=[A], shot_refs=[B], shots=3)
    report = audit_reference_files(project, workspace=tmp_path)
    assert not report.references_ready
    assert report.unique_references == 2
    assert report.valid_unique_references == 1
    assert report.shots_with_valid_references == 0
    assert _codes(report) == ["REFERENCE_FILE_MISSING"] * 3
    assert [f.shot_id for f in report.findings] == [
        shot.shot_id for shot in project.scenes[0].shots
    ]


def test_corrupt_png_is_rejected_without_file_name_or_bytes_in_output(tmp_path):
    directory = tmp_path / "video-assets"
    directory.mkdir()
    (directory / f"{A}.png").write_bytes(b"SECRET_USER_IMAGE_BYTES_NOT_A_PNG")
    report = audit_reference_files(_project(refs=[A]), workspace=tmp_path)
    assert not report.references_ready
    assert _codes(report) == ["REFERENCE_IMAGE_INVALID", "REFERENCE_IMAGE_INVALID"]
    payload = json.dumps(report.as_dict())
    for secret in (
        "SECRET_USER_IMAGE_BYTES_NOT_A_PNG", "SECRET SHOT",
        "SECRET MASTER SCREENPLAY", str(tmp_path), A,
    ):
        assert secret not in payload


def test_fake_png_named_file_with_jpeg_contents_is_rejected(tmp_path):
    path = _png(tmp_path, A)
    Image.new("RGB", (3, 3)).save(path, format="JPEG")
    report = audit_reference_files(_project(refs=[A]), workspace=tmp_path)
    assert _codes(report) == ["REFERENCE_FORMAT_INVALID"] * 2


def test_pixels_guard_is_enforced_without_allocating_large_image(tmp_path, monkeypatch):
    import app.video.cinematic_reference_preflight as verifier
    _png(tmp_path, A, width=2, height=2)
    monkeypatch.setattr(verifier, "_MAX_PIXELS", 3)
    report = audit_reference_files(_project(refs=[A]), workspace=tmp_path)
    assert _codes(report) == ["REFERENCE_TOO_MANY_PIXELS"] * 2


def test_missing_workspace_does_not_create_it(tmp_path):
    missing = tmp_path / "not-created"
    report = audit_reference_files(_project(refs=[A]), workspace=missing)
    assert "WORKSPACE_UNAVAILABLE" in _codes(report)
    assert report.shots_with_valid_references == 0
    assert report.valid_unique_references == 0
    assert not missing.exists()


def test_missing_asset_directory_does_not_create_it(tmp_path):
    result = audit_reference_files(_project(refs=[A]), workspace=tmp_path)
    assert _codes(result) == ["REFERENCE_DIRECTORY_UNAVAILABLE"]
    assert not (tmp_path / "video-assets").exists()


def test_symlink_asset_directory_is_rejected(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    workspace = tmp_path / "studio"
    workspace.mkdir()
    (workspace / "video-assets").symlink_to(outside, target_is_directory=True)
    result = audit_reference_files(_project(refs=[A]), workspace=workspace)
    assert _codes(result) == ["REFERENCE_DIRECTORY_UNAVAILABLE"]
    assert not result.references_ready


def test_symlink_image_does_not_follow_private_external_file(tmp_path):
    outside = tmp_path / "external.png"
    Image.new("RGB", (4, 4)).save(outside, format="PNG")
    directory = tmp_path / "video-assets"
    directory.mkdir()
    (directory / f"{A}.png").symlink_to(outside)
    report = audit_reference_files(_project(refs=[A]), workspace=tmp_path)
    assert _codes(report) == ["REFERENCE_PATH_UNSAFE"] * 2


def test_no_references_will_not_pretend_the_project_can_render(tmp_path):
    (tmp_path / "video-assets").mkdir()
    report = audit_reference_files(_project(), workspace=tmp_path)
    assert _codes(report) == ["NO_SOURCE_REFERENCE"] * 2
    assert not report.references_ready


def test_readiness_is_snapshot_not_mutation(tmp_path):
    image = _png(tmp_path, A)
    project = _project(refs=[A])
    project_before = project.model_dump(mode="json")
    source_before = image.read_bytes()
    first = audit_reference_files(project, workspace=tmp_path)
    second = audit_reference_files(project, workspace=tmp_path)
    assert first == second
    assert project.model_dump(mode="json") == project_before
    assert image.read_bytes() == source_before


def test_invalid_identifier_even_if_validation_was_bypassed(tmp_path):
    (tmp_path / "video-assets").mkdir()
    project = _project(refs=[A])
    project.reference_image_ids = [A]  # validated model before unsafe model_copy below
    tampered = project.model_copy(update={"reference_image_ids": ["../SECRET_FILE"]})
    report = audit_reference_files(tampered, workspace=tmp_path)
    assert _codes(report) == ["REFERENCE_ID_INVALID"] * 2
    assert "../SECRET_FILE" not in json.dumps(report.as_dict())


def test_zero_shots_is_not_ready_even_if_project_has_a_png(tmp_path):
    _png(tmp_path, A)
    result = audit_reference_files(_project(refs=[A], shots=0), workspace=tmp_path)
    assert result.shot_count == 0
    assert result.valid_unique_references == 0
    assert _codes(result) == ["NO_SHOTS"]
    assert not result.references_ready


def test_pillow_decompression_bomb_guard_reports_neutral_size_error(tmp_path, monkeypatch):
    _png(tmp_path, A, width=3, height=3)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1)
    report = audit_reference_files(_project(refs=[A]), workspace=tmp_path)
    assert _codes(report) == ["REFERENCE_TOO_MANY_PIXELS"] * 2
    assert not report.references_ready


def test_local_png_byte_limit_matches_image_uploader_and_avoids_decode(tmp_path):
    source = _png(tmp_path, A)
    # Create sparse trailing content without allocating a 13 MiB buffer.
    with source.open("ab") as handle:
        handle.truncate(12 * 1024 * 1024 + 1)
    report = audit_reference_files(_project(refs=[A]), workspace=tmp_path)
    assert _codes(report) == ["REFERENCE_TOO_MANY_BYTES"] * 2
    assert not report.references_ready


def test_fifo_reference_is_rejected_without_blocking(tmp_path):
    import os
    if not hasattr(os, "mkfifo") or not hasattr(os, "O_NONBLOCK"):
        pytest.skip("FIFO probe requires POSIX nonblocking open")
    directory = tmp_path / "video-assets"
    directory.mkdir()
    os.mkfifo(directory / (A + ".png"))
    report = audit_reference_files(_project(refs=[A]), workspace=tmp_path)
    assert _codes(report) == ["REFERENCE_PATH_UNSAFE"] * 2
    assert not report.references_ready


def test_symlink_inserted_between_path_check_and_open_is_rejected(tmp_path, monkeypatch):
    import os
    import app.video.cinematic_reference_preflight as verifier

    if not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("O_NOFOLLOW is not available on this platform")
    source = _png(tmp_path, A)
    outside = tmp_path / "PRIVATE_EXTERNAL.png"
    Image.new("RGB", (2, 2)).save(outside)
    original_open = os.open
    attempted = False

    def swap_just_before_open(path, flags, *args, **kwargs):
        nonlocal attempted
        if not attempted and Path(path) == source:
            attempted = True
            source.unlink()
            source.symlink_to(outside)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(verifier.os, "open", swap_just_before_open)
    report = audit_reference_files(_project(refs=[A]), workspace=tmp_path)
    assert attempted
    assert _codes(report) == ["REFERENCE_PATH_UNSAFE"] * 2
    assert not report.references_ready
    assert str(outside) not in json.dumps(report.as_dict())


def test_both_png_validation_passes_use_one_original_inode(tmp_path, monkeypatch):
    import app.video.cinematic_reference_preflight as verifier

    source = _png(tmp_path, A)
    outside = tmp_path / "PRIVATE_INVALID.png"
    outside.write_bytes(b"PRIVATE_REPLACEMENT_NOT_A_PNG")
    original_image_open = Image.open
    opened = 0

    def swap_after_decode(file, *args, **kwargs):
        nonlocal opened
        opened += 1
        if opened == 2:
            source.unlink()
            source.symlink_to(outside)
        return original_image_open(file, *args, **kwargs)

    monkeypatch.setattr(verifier.Image, "open", swap_after_decode)
    report = audit_reference_files(_project(refs=[A]), workspace=tmp_path)
    assert opened == 2
    assert report.references_ready
    assert report.unique_references == report.valid_unique_references == 1
    # Readiness is ephemeral, and the next inspection correctly detects the
    # path change instead of pretending that earlier evidence is durable.
    second = audit_reference_files(_project(refs=[A]), workspace=tmp_path)
    assert _codes(second) == ["REFERENCE_PATH_UNSAFE"] * 2
    assert not second.references_ready
