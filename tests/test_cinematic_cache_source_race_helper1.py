"""Real-media cache race: source bytes must remain bound through cache return.

A synthetic source MP4 is changed immediately *after* the assembler hashes
its bytes but before it checks a previously verified cached master. This is
a deterministic interleaving, not a claimed remote exploit or owner-media test.
The cached result must not certify footage from superseded source bytes.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from test_cinematic_assembly_queue import _ready_project


def _color_video(ffmpeg: str, path: Path, color: str) -> None:
    subprocess.run(
        [ffmpeg, "-nostdin", "-y", "-v", "error", "-f", "lavfi",
         "-i", f"color=c={color}:s=160x90:r=24:d=2",
         "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        capture_output=True, check=True, timeout=90,
    )


def _full_decode(ffmpeg: str, path: Path) -> None:
    subprocess.run(
        [ffmpeg, "-nostdin", "-v", "error", "-xerror", "-i", str(path),
         "-map", "0:v:0", "-an", "-f", "null", "-"],
        capture_output=True, check=True, timeout=90,
    )


def _first_pixel(ffmpeg: str, path: Path) -> bytes:
    result = subprocess.run(
        [ffmpeg, "-nostdin", "-v", "error", "-i", str(path),
         "-frames:v", "1", "-vf", "scale=1:1:flags=area,format=rgb24",
         "-f", "rawvideo", "pipe:1"],
        capture_output=True, check=True, timeout=90,
    )
    assert len(result.stdout) == 3
    return result.stdout


def test_cached_master_revalidates_source_bytes_changed_after_source_hash(
    monkeypatch, tmp_path: Path,
):
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        if os.getenv("CINEMATIC_REQUIRE_REAL_MEDIA") == "1":
            pytest.fail("Cached source-race QA requires real FFmpeg and FFprobe")
        pytest.skip("FFmpeg/FFprobe unavailable; ordinary CI is not media proof")

    _, service, storage, _, project = _ready_project(monkeypatch, tmp_path)
    from app.video.cinematic_requests import AssembleMasterRequest

    source = storage.video_asset_path("4" * 32, "mp4")
    replacement = storage.video_asset_path("5" * 32, "mp4")
    _color_video(ffmpeg, source, "red")
    _color_video(ffmpeg, replacement, "blue")
    red_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    blue_bytes = replacement.read_bytes()
    blue_sha = hashlib.sha256(blue_bytes).hexdigest()
    assert red_sha != blue_sha

    request = AssembleMasterRequest(expected_revision=project.revision)
    original = service.assemble_project_master(project.id, request)
    original_path = storage.video_asset_path(original["asset_id"], "mp4")
    assert original["status"] == "ready"
    assert original["source_asset_hashes"] == [red_sha]
    assert original["probe"]["frame_count"] == 48
    assert hashlib.sha256(original_path.read_bytes()).hexdigest() == original["sha256"]
    _full_decode(ffmpeg, original_path)
    red_pixel = _first_pixel(ffmpeg, original_path)
    assert red_pixel[0] > red_pixel[2] + 60, tuple(red_pixel)

    # The repeat request hashes the RED source and then verifies a cached
    # master. Change the source bytes just after that digest is returned.
    # An old RED cache hit is now stale even though the project revision
    # and original cached MP4's SHA remain unchanged.
    real_digest = hashlib.file_digest
    swapped = []

    def replace_after_source_digest(handle, algorithm):
        digest = real_digest(handle, algorithm)
        if Path(handle.name) == source and not swapped:
            source.write_bytes(blue_bytes)
            swapped.append(True)
        return digest

    monkeypatch.setattr(service.hashlib, "file_digest", replace_after_source_digest)
    try:
        result = service.assemble_project_master(project.id, request)
    except (RuntimeError, ValueError) as exc:
        assert swapped, "The source-byte interleaving was not exercised"
        assert re.search(r"source|input|changed|stale|modified", str(exc), re.I), (
            "Only an explicit source-freshness rejection is an acceptable failure"
        )
        assert hashlib.sha256(source.read_bytes()).hexdigest() == blue_sha
        return

    assert swapped, "The source-byte interleaving was not exercised"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == blue_sha
    assert result["status"] == "ready"
    output_path = storage.video_asset_path(result["asset_id"], "mp4")
    _full_decode(ffmpeg, output_path)
    blue_pixel = _first_pixel(ffmpeg, output_path)
    assert blue_pixel[2] > blue_pixel[0] + 60, (
        "Cached master returned old RED frames after its source changed to BLUE"
    )
    assert result["source_asset_hashes"] == [blue_sha], (
        "Ready master attested to a stale pre-swap source SHA-256"
    )
    assert result["sha256"] == hashlib.sha256(output_path.read_bytes()).hexdigest()
