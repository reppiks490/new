"""QA33: POSIX private cinematic workspace, SQLite, and FFmpeg master modes.

All inputs are synthetic. A restrictive parent pytest tmpdir can mask an
insecure child, so test the child modes themselves under a controlled 022 umask.
These are intentionally strict application regressions until production is
hardened; they do not establish unauthorized access to any owner's files.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import subprocess

import pytest

from app.video import cinematic_models as models, cinematic_service as service
from app.video.cinematic_requests import AssembleMasterRequest
from app.video.storage import put_video_record, video_asset_path

pytestmark = [
    pytest.mark.skipif(os.name != "posix", reason="POSIX file modes only"),
    pytest.mark.skipif(
        os.getenv("CINEMATIC_REQUIRE_PRIVATE_MODES_QA") != "1",
        reason="Strict expected-red privacy regression runs in dedicated QA33 workflow",
    ),
]


@pytest.fixture
def studio_under_standard_umask(monkeypatch, tmp_path):
    workspace = tmp_path / "studio"
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(workspace))
    old_umask = os.umask(0o022)
    try:
        yield workspace
    finally:
        os.umask(old_umask)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _synthetic_project():
    return service.create_project(models.ProjectCreateRequest(
        title="Synthetic permissions test",
        master_prompt="Synthetic content only; no owner footage or private text",
        target_duration_seconds=10.0,
        delivery_fps=24,
        delivery_resolution="480p",
    ))


def test_studio_workspace_is_not_accessible_to_other_local_users(studio_under_standard_umask):
    _synthetic_project()
    mode = _mode(studio_under_standard_umask)
    assert mode & 0o077 == 0, (
        f"Studio workspace created with mode {mode:04o}; "
        "other local users must not traverse private project storage"
    )


def test_private_sqlite_database_is_not_readable_by_other_local_users(studio_under_standard_umask):
    _synthetic_project()
    database = studio_under_standard_umask / "studio.sqlite"
    assert database.is_file()
    mode = _mode(database)
    assert mode & 0o077 == 0, (
        f"Private project SQLite database created with mode {mode:04o}; "
        "contains authored screenplay/project records"
    )


def test_private_video_asset_directory_is_not_traversable_by_other_local_users(studio_under_standard_umask):
    video_asset_path("1" * 32, "mp4")
    directory = studio_under_standard_umask / "video-assets"
    mode = _mode(directory)
    assert mode & 0o077 == 0, (
        f"Private video-assets directory created with mode {mode:04o}"
    )


def test_real_synthetic_master_file_is_owner_only(studio_under_standard_umask, tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        if os.getenv("CINEMATIC_REQUIRE_PRIVATE_MODES_QA") == "1":
            pytest.fail("FFmpeg and FFprobe required for strict private-file QA")
        pytest.skip("FFmpeg and FFprobe required")

    project = _synthetic_project()
    shot = models.CinematicShot(
        shot_id="2" * 32, ordinal=1, title="Synthetic shot",
        prompt="Synthetic only", duration_seconds=10.0,
    )
    scene = models.CinematicScene(
        scene_id="3" * 32, ordinal=1, title="Synthetic scene",
        target_duration_seconds=10.0, shots=[shot],
    )
    project = service.update_project(
        project.id, models.ProjectUpdateRequest(
            expected_revision=project.revision, scenes=[scene],
        ),
    )

    source = tmp_path / "synthetic.mp4"
    subprocess.run([
        ffmpeg, "-nostdin", "-y", "-v", "error",
        "-f", "lavfi", "-i", "color=c=blue:s=160x90:r=24:d=10",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
    ], check=True, capture_output=True, timeout=60)

    asset_id = "4" * 32
    shutil.copyfile(source, video_asset_path(asset_id, "mp4"))
    job = put_video_record("video_job", {
        "status": "succeeded", "project_id": project.id,
        "scene_id": scene.scene_id, "shot_id": shot.shot_id,
        "asset_id": asset_id,
    })
    linked = shot.model_copy(update={"latest_job_id": job["id"]})
    project = service.update_project(
        project.id, models.ProjectUpdateRequest(
            expected_revision=project.revision,
            scenes=[scene.model_copy(update={"shots": [linked]})],
        ),
    )
    master = service.assemble_project_master(
        project.id, AssembleMasterRequest(expected_revision=project.revision),
    )
    assert master["probe"]["frame_count"] == 240
    output = video_asset_path(master["asset_id"], "mp4")
    assert output.is_file()
    mode = _mode(output)
    assert mode & 0o077 == 0, (
        f"Actual synthetic FFmpeg master created with mode {mode:04o}; "
        "authenticated HTTP access does not constrain local filesystem access"
    )


def test_independent_private_file_mode_control(studio_under_standard_umask):
    """Demonstrate owner-only creation is feasible under the same umask."""
    path = studio_under_standard_umask / "private-control.bin"
    path.parent.mkdir(exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    assert _mode(path) == 0o600
