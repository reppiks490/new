"""Real-media guard: an invalid newest cache entry must not hide an older valid master.

Independent QA-owned test. All video is locally generated synthetic color media;
no private footage, GPU, cloud generation, or paid services are required.
"""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from test_cinematic_assembly_queue import _ready_project


@pytest.mark.parametrize("unrelated_newer", [0, 99], ids=["adjacent", "older_than_history_window"])
def test_corrupt_newer_master_falls_back_to_verified_older(
    monkeypatch, tmp_path, unrelated_newer,
):
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        if os.getenv("CINEMATIC_REQUIRE_REAL_MEDIA") == "1":
            pytest.fail("Cache candidate QA requires real FFmpeg and FFprobe")
        pytest.skip("FFmpeg/FFprobe unavailable")

    _, service, storage, _, project = _ready_project(monkeypatch, tmp_path)
    from app.video.cinematic_requests import AssembleMasterRequest

    source = storage.video_asset_path("4" * 32, "mp4")
    subprocess.run(
        [ffmpeg, "-nostdin", "-y", "-v", "error", "-f", "lavfi",
         "-i", "color=c=blue:s=160x90:r=24:d=2", "-an", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", str(source)],
        check=True, capture_output=True, timeout=60,
    )
    request = AssembleMasterRequest(expected_revision=project.revision)
    original = service.assemble_project_master(project.id, request)
    assert original["status"] == "ready"
    assert original["probe"]["probe_metadata_verified"] is True
    assert original["probe"]["frame_count"] == 48
    output = storage.video_asset_path(original["asset_id"], "mp4")
    subprocess.run(
        [ffmpeg, "-nostdin", "-v", "error", "-xerror", "-i", str(output),
         "-an", "-f", "null", "-"],
        check=True, capture_output=True, timeout=60,
    )

    # A newer same-project/same-source candidate advertises verification,
    # but its referenced asset is missing. It must be skipped.
    missing_asset = "d" * 32
    assert not storage.video_asset_path(missing_asset, "mp4").exists()
    storage.put_video_record(
        "video_master",
        {
            "status": "ready", "project_id": project.id,
            "project_revision": project.revision,
            "source_digest": original["source_digest"],
            "asset_id": missing_asset, "sha256": "f" * 64,
            "probe": {"probe_metadata_verified": True},
            "actual_video_probe_verified": True,
        },
        identifier="e" * 32,
    )

    # With 99 unrelated newer records, the valid original is 101st.
    # The global LIMIT 100 loses it despite intact on-disk verification.
    for index in range(unrelated_newer):
        storage.put_video_record(
            "video_master",
            {"status": "ready", "project_id": "f" * 32,
             "source_digest": f"{index:064x}",
             "asset_id": f"{index + 1000:032x}", "sha256": "0" * 64},
            identifier=f"{index + 2000:032x}",
        )

    assert storage.get_video_record("video_master", original["id"])["sha256"] == original["sha256"]

    def unexpected_reencode(*_args, **_kwargs):
        raise AssertionError("Corrupt newer cache entry hid a valid older master")

    monkeypatch.setattr(service, "_run_master_ffmpeg", unexpected_reencode)
    reused = service.assemble_project_master(project.id, request)
    assert reused["id"] == original["id"]
    assert reused["sha256"] == original["sha256"]
