"""Real-media regression: verified master cache must not age out at 100 records.

Uses only generated color bars and a temporary SQLite workspace.  The first
assembly really executes FFmpeg/ffprobe and decodes the complete MP4; the
second must reuse its byte-verified master without invoking FFmpeg again.
"""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from test_cinematic_assembly_queue import _ready_project


def test_verified_master_cache_survives_unrelated_history_over_100(monkeypatch, tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        if os.getenv("CINEMATIC_REQUIRE_REAL_MEDIA") == "1":
            pytest.fail("Cache history proof requires real FFmpeg and FFprobe")
        pytest.skip("FFmpeg/FFprobe unavailable in this Python environment")

    _, service, storage, _, project = _ready_project(monkeypatch, tmp_path)
    from app.video.cinematic_requests import AssembleMasterRequest

    source = storage.video_asset_path("4" * 32, "mp4")
    subprocess.run(
        [
            ffmpeg, "-nostdin", "-y", "-v", "error", "-f", "lavfi",
            "-i", "color=c=red:s=160x90:r=24:d=2",
            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(source),
        ],
        check=True, capture_output=True, timeout=60,
    )
    request = AssembleMasterRequest(expected_revision=project.revision)
    original = service.assemble_project_master(project.id, request)
    assert original["status"] == "ready"
    assert original["probe"]["probe_metadata_verified"] is True
    assert original["probe"]["frame_count"] == 48
    master_path = storage.video_asset_path(original["asset_id"], "mp4")
    subprocess.run(
        [ffmpeg, "-nostdin", "-v", "error", "-xerror", "-i",
         str(master_path), "-an", "-f", "null", "-"],
        check=True, capture_output=True, timeout=60,
    )

    # Many unrelated master records must not hide this valid, byte-verified
    # cache entry. The generic storage list currently returns only 100 newest
    # records across all projects; production cache lookup must not rely on it.
    for index in range(101):
        storage.put_video_record(
            "video_master",
            {
                "status": "ready",
                "project_id": "f" * 32,
                "source_digest": f"{index:064x}",
                "asset_id": f"{index + 1000:032x}",
                "sha256": "0" * 64,
            },
            identifier=f"{index + 2000:032x}",
        )
    assert storage.get_video_record("video_master", original["id"])["sha256"] == original["sha256"]

    def unexpected_reencode(*_args, **_kwargs):
        raise AssertionError("Unchanged verified master was needlessly re-encoded")

    monkeypatch.setattr(service, "_run_master_ffmpeg", unexpected_reencode)
    reused = service.assemble_project_master(project.id, request)
    assert reused["id"] == original["id"]
    assert reused["sha256"] == original["sha256"]
