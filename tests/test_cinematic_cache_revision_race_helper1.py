"""Real-media regression: a cached master must not outlive its request revision.

An update to a project's revision during the cached MP4 hash check must
fail closed. The test uses one real synthetic FFmpeg master and a deterministic
single-threaded interleaving, not owner footage, inference or paid services.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from test_cinematic_assembly_queue import _ready_project


def test_cached_master_rejects_revision_change_during_cache_verification(
    monkeypatch, tmp_path: Path,
):
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        if os.getenv("CINEMATIC_REQUIRE_REAL_MEDIA") == "1":
            pytest.fail("Cache revision-race acceptance requires FFmpeg and FFprobe")
        pytest.skip("Real-media tools unavailable in ordinary Python matrix")

    models, service, storage, _, project = _ready_project(monkeypatch, tmp_path)
    from app.video.cinematic_requests import AssembleMasterRequest

    source = storage.video_asset_path("4" * 32, "mp4")
    subprocess.run(
        [
            ffmpeg, "-nostdin", "-y", "-v", "error", "-f", "lavfi",
            "-i", "color=c=red:s=160x90:r=24:d=2",
            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
        ],
        check=True, capture_output=True, timeout=60,
    )
    request = AssembleMasterRequest(expected_revision=project.revision)
    original = service.assemble_project_master(project.id, request)
    assert original["status"] == "ready"
    assert original["probe"]["probe_metadata_verified"] is True
    assert original["probe"]["frame_count"] == 48
    output = storage.video_asset_path(original["asset_id"], "mp4")
    assert hashlib.sha256(output.read_bytes()).hexdigest() == original["sha256"]
    subprocess.run(
        [
            ffmpeg, "-nostdin", "-v", "error", "-xerror", "-i", str(output),
            "-an", "-f", "null", "-",
        ],
        check=True, capture_output=True, timeout=60,
    )

    # The first file_digest in a repeated request hashes the source; the
    # second hashes the existing master during cache verification. Inject an
    # otherwise harmless project-title revision update at that exact boundary.
    # A revision check performed only before cache verification is stale.
    real_file_digest = hashlib.file_digest
    triggered = []
    def edit_while_verifying_cached_master(handle, algorithm):
        if Path(handle.name) == output and not triggered:
            triggered.append(True)
            edited = service.update_project(
                project.id,
                models.ProjectUpdateRequest(
                    expected_revision=project.revision,
                    title="Changed while verifying cached master",
                ),
            )
            assert edited.revision == project.revision + 1
        return real_file_digest(handle, algorithm)

    def unexpected_reencode(*_args, **_kwargs):
        raise AssertionError("An unchanged source must take the cache path")

    monkeypatch.setattr(service.hashlib, "file_digest", edit_while_verifying_cached_master)
    monkeypatch.setattr(service, "_run_master_ffmpeg", unexpected_reencode)
    try:
        stale_result = service.assemble_project_master(project.id, request)
    except service.ProjectRevisionConflict:
        pass  # Correct: the requested revision became stale before response.
    else:
        pytest.fail(
            "Cached master was returned after project revision changed "
            f"from {project.revision} to {service.get_project(project.id).revision}; "
            f"returned master id={stale_result['id']}"
        )

    assert triggered, "The revision-change interleaving was not exercised"
    assert service.get_project(project.id).revision == project.revision + 1
    assert storage.get_video_record("video_master", original["id"])["sha256"] == original["sha256"]
    assert len(storage.list_video_records("video_master")) == 1
