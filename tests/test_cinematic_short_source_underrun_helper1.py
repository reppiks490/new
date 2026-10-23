"""Real-media gate: a short shot must not silently become a full-length master.

All inputs are locally generated synthetic test patterns. The authored shot is
2 seconds/48 frames, while the real source clip contains only 1 second/24
frames. The current FFmpeg tpad=clone path can conceal the deficit by repeating
the last frame and publishing a normal ready master. This QA test requires an
explicit fail-closed under-run decision, not a visually frozen "complete" film.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from test_cinematic_assembly_queue import _ready_project


def _run(command: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, check=True, timeout=timeout)


def _frame_count(ffprobe: str, path: Path) -> int:
    result = _run([
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=nb_frames", "-of", "json", str(path),
    ])
    return int(json.loads(result.stdout)["streams"][0]["nb_frames"])


def test_short_source_cannot_be_published_as_fully_rendered_master(monkeypatch, tmp_path: Path):
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        if os.getenv("CINEMATIC_REQUIRE_REAL_MEDIA") == "1":
            pytest.fail("Strict under-run QA requires genuine FFmpeg and FFprobe")
        pytest.skip("Real-media tools unavailable in ordinary Python CI")

    _, service, storage, _, project = _ready_project(monkeypatch, tmp_path)
    from app.video.cinematic_requests import AssembleMasterRequest

    source = storage.video_asset_path("4" * 32, "mp4")
    _run([
        ffmpeg, "-nostdin", "-y", "-v", "error",
        "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=24:duration=1",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(source),
    ])
    assert _frame_count(ffprobe, source) == 24
    assert project.scenes[0].shots[0].duration_seconds == 2
    assert service.project_render_status(project.id)["ready_for_assembly"]

    try:
        master = service.assemble_project_master(
            project.id, AssembleMasterRequest(expected_revision=project.revision),
        )
    except (service.MasterAssemblyNotReady, RuntimeError, ValueError) as exc:
        # A future fail-closed implementation must identify the source deficit;
        # an unrelated subprocess/fixture error is not a passing acceptance.
        message = str(exc).lower()
        assert any(word in message for word in ("short", "duration", "frame", "under-run", "source")), message
        assert not [
            row for row in storage.list_video_records("video_master")
            if row.get("project_id") == project.id and row.get("status") == "ready"
        ]
        return

    output = storage.video_asset_path(master["asset_id"], "mp4")
    assert master["status"] == "ready"
    assert _frame_count(ffprobe, output) == 48

    # Independently prove the generated master is decodable, yet contains
    # synthetic duplicated late frames rather than 48 genuine source frames.
    _run([ffmpeg, "-nostdin", "-v", "error", "-xerror",
          "-i", str(output), "-map", "0:v:0", "-an", "-f", "null", "-"])
    sample = _run([
        ffmpeg, "-nostdin", "-v", "error", "-i", str(output),
        "-vf", r"select=eq(n\\,28)+eq(n\\,45),scale=8:8",
        "-vsync", "0", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
    ]).stdout
    assert len(sample) == 2 * 8 * 8 * 3, "Fixture did not decode both late master frames"
    assert sample[:192] == sample[192:], "Expected tpad-cloned late frames were not observed"
    pytest.fail(
        "An authored 48-frame shot with only 24 genuine source frames was "
        "silently extended with repeated frames and published as ready"
    )
