"""Test-first real-media proof: source bytes cannot change under a master hash.

A deterministic local hook swaps a synthetic source MP4 *after* the master
assembler hashes inputs but *before* FFmpeg opens the source. This tests the
input-provenance TOCTOU boundary without owner media or a GPU.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess

import pytest

from test_cinematic_assembly_queue import _ready_project


def _make_color_clip(ffmpeg: str, path, color: str) -> None:
    subprocess.run(
        [
            ffmpeg, "-nostdin", "-y", "-v", "error", "-f", "lavfi",
            "-i", f"color=c={color}:s=160x90:r=24:d=2",
            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True, capture_output=True, timeout=60,
    )


def test_master_never_certifies_pre_swap_hash_for_post_swap_media(monkeypatch, tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        if os.getenv("CINEMATIC_REQUIRE_REAL_MEDIA") == "1":
            pytest.fail("Source-byte race proof requires real FFmpeg and FFprobe")
        pytest.skip("FFmpeg/FFprobe unavailable in this Python environment")

    _, service, storage, _, project = _ready_project(monkeypatch, tmp_path)
    from app.video.cinematic_requests import AssembleMasterRequest

    source = storage.video_asset_path("4" * 32, "mp4")
    replacement = storage.video_asset_path("5" * 32, "mp4")
    _make_color_clip(ffmpeg, source, "red")
    _make_color_clip(ffmpeg, replacement, "blue")
    before_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    replacement_bytes = replacement.read_bytes()
    after_sha = hashlib.sha256(replacement_bytes).hexdigest()
    assert before_sha != after_sha

    # _run_master_ffmpeg is invoked only after source_identity is computed.
    # Replacing a file at this exact seam is a reproducible concurrent-writer
    # interleaving, not an actual background race or private file operation.
    real_run = subprocess.run
    swaps = []

    def replace_before_ffmpeg(command, **kwargs):
        assert str(source) in command
        assert not swaps
        source.write_bytes(replacement_bytes)
        swaps.append(True)
        return real_run(command, **kwargs)

    monkeypatch.setattr(service, "_run_master_ffmpeg", replace_before_ffmpeg)
    try:
        master = service.assemble_project_master(
            project.id, AssembleMasterRequest(expected_revision=project.revision)
        )
    except (RuntimeError, ValueError) as exc:
        # Fail-closed is acceptable only for an explicit input-freshness
        # rejection; an unrelated encoder failure must not satisfy the test.
        assert swaps
        assert re.search(r"source|input|changed|stale|modified", str(exc), re.I), str(exc)
        assert not [
            record for record in storage.list_video_records("video_master")
            if record.get("project_id") == project.id and record.get("status") == "ready"
        ]
        return

    assert swaps, "The deterministic source swap was not exercised"
    assert master["status"] == "ready"
    assert master["probe"]["probe_metadata_verified"] is True
    assert master["probe"]["frame_count"] == 48
    master_path = storage.video_asset_path(master["asset_id"], "mp4")
    real_run(
        [ffmpeg, "-nostdin", "-v", "error", "-xerror", "-i", str(master_path),
         "-an", "-f", "null", "-"],
        check=True, capture_output=True, timeout=60,
    )
    # Check the actual decoded first frame: the encoder consumed BLUE media,
    # not the RED bytes hashed before the swap.
    frame = real_run(
        [ffmpeg, "-nostdin", "-v", "error", "-i", str(master_path),
         "-frames:v", "1", "-vf", "scale=1:1:flags=area,format=rgb24",
         "-f", "rawvideo", "pipe:1"],
        check=True, capture_output=True, timeout=60,
    ).stdout
    assert len(frame) == 3
    assert frame[2] > frame[0] + 60, f"Unexpected decoded color channels: {tuple(frame)}"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == after_sha

    # A ready master must never claim the old RED source digest after
    # encoding BLUE source bytes. A source-owner fix may fail closed or
    # rehash/retry, but must not persist a false provenance attestation.
    persisted = storage.get_video_record("video_master", master["id"])
    assert persisted["source_asset_hashes"] == [after_sha], (
        "Master published stale pre-swap source hash for post-swap decoded media"
    )
