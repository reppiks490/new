"""Test-first real-media gate: metadata-valid but undecodable masters are not ready.

Only synthetic FFmpeg video is used. The seam lets FFmpeg finish successfully,
then truncates its MP4 media payload while retaining the faststart moov metadata.
ffprobe still reports the correct frame count, but a full strict decode fails.
This is a deterministic output-integrity test, not a user-footage claim.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from test_cinematic_assembly_queue import _ready_project


def test_master_rejects_metadata_valid_but_undecodable_mp4(monkeypatch, tmp_path: Path):
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        if os.getenv("CINEMATIC_REQUIRE_REAL_MEDIA") == "1":
            pytest.fail("Strict master decode QA requires real FFmpeg and FFprobe")
        pytest.skip("Real-media tools unavailable in ordinary Python matrix")

    _, service, storage, _, project = _ready_project(monkeypatch, tmp_path)
    from app.video.cinematic_requests import AssembleMasterRequest

    source = storage.video_asset_path("4" * 32, "mp4")
    subprocess.run(
        [
            ffmpeg, "-nostdin", "-y", "-v", "error", "-f", "lavfi",
            "-i", "testsrc2=size=160x90:rate=24:duration=2",
            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(source),
        ],
        check=True, capture_output=True, timeout=60,
    )

    actual_run = subprocess.run
    damaged = []

    def truncate_after_successful_encode(command, **kwargs):
        execution = actual_run(command, **kwargs)
        if execution.returncode != 0:
            return execution
        output = Path(command[-1])
        full = output.read_bytes()
        assert len(full) > 1000 and b"moov" in full[: min(8192, len(full))]
        for fraction in (0.75, 0.65, 0.55):
            output.write_bytes(full[: int(len(full) * fraction)])
            metadata = actual_run(
                [
                    ffprobe, "-v", "error", "-select_streams", "v:0",
                    "-show_entries",
                    "stream=codec_type,codec_name,width,height,avg_frame_rate,nb_frames,duration:format=duration",
                    "-of", "json", str(output),
                ],
                capture_output=True, text=True, timeout=60,
            )
            strict_decode = actual_run(
                [
                    ffmpeg, "-nostdin", "-v", "error", "-xerror",
                    "-i", str(output), "-map", "0:v:0", "-an", "-f", "null", "-",
                ],
                capture_output=True, timeout=60,
            )
            if metadata.returncode != 0 or strict_decode.returncode == 0:
                continue
            probe = json.loads(metadata.stdout)
            video = next((s for s in probe.get("streams", [])
                          if s.get("codec_type") == "video"), None)
            if (video and video.get("codec_name") == "h264"
                    and int(video.get("nb_frames", 0)) == 48
                    and video.get("avg_frame_rate") == "24/1"):
                damaged.append((output, strict_decode.stderr[:300]))
                break
        assert damaged, "Fixture must retain ffprobe metadata but fail full decode"
        return execution

    monkeypatch.setattr(service, "_run_master_ffmpeg", truncate_after_successful_encode)

    try:
        master = service.assemble_project_master(
            project.id, AssembleMasterRequest(expected_revision=project.revision)
        )
    except (RuntimeError, ValueError):
        # Correct fail-closed behavior: the corrupt output must not be ready.
        assert damaged, "The deterministic post-encode corruption was not exercised"
        assert not [
            record for record in storage.list_video_records("video_master")
            if record.get("project_id") == project.id and record.get("status") == "ready"
        ]
        return

    assert damaged, "The deterministic post-encode corruption was not exercised"
    assert master.get("status") != "ready", (
        "Metadata-valid but undecodable truncated MP4 was published as ready"
    )
    assert not [
        record for record in storage.list_video_records("video_master")
        if record.get("project_id") == project.id and record.get("status") == "ready"
    ]
