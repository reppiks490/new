"""Real-media QA: a cache-hit SHA check must not certify a swapped output file.

This deterministic local filesystem interleaving swaps an already-verified RED
master for a fully decodable BLUE MP4 immediately *after* its SHA-256 has been
read but before the cached record is returned. No owner footage, credentials,
network media provider or paid service is involved. It is not a remote exploit.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from test_cinematic_assembly_queue import _ready_project


def _encode_color(ffmpeg: str, path: Path, color: str, size: str) -> None:
    subprocess.run(
        [ffmpeg, "-nostdin", "-y", "-v", "error", "-f", "lavfi",
         "-i", f"color=c={color}:s={size}:r=24:d=2",
         "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", str(path)],
        capture_output=True, check=True, timeout=90,
    )


def _probe_frames(ffprobe: str, path: Path) -> int:
    output = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=nb_frames", "-of", "json", str(path)],
        capture_output=True, text=True, check=True, timeout=90,
    )
    return int(json.loads(output.stdout)["streams"][0]["nb_frames"])


def _decode_and_pixel(ffmpeg: str, path: Path) -> bytes:
    subprocess.run(
        [ffmpeg, "-nostdin", "-v", "error", "-xerror", "-i", str(path),
         "-map", "0:v:0", "-an", "-f", "null", "-"],
        capture_output=True, check=True, timeout=90,
    )
    output = subprocess.run(
        [ffmpeg, "-nostdin", "-v", "error", "-i", str(path),
         "-frames:v", "1", "-vf", "scale=1:1:flags=area,format=rgb24",
         "-f", "rawvideo", "pipe:1"],
        capture_output=True, check=True, timeout=90,
    )
    assert len(output.stdout) == 3
    return output.stdout


def test_cached_master_rejects_output_swap_after_sha_verification(
    monkeypatch, tmp_path: Path,
):
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        if os.getenv("CINEMATIC_REQUIRE_REAL_MEDIA") == "1":
            pytest.fail("Output-swap QA requires real FFmpeg and FFprobe")
        pytest.skip("FFmpeg/FFprobe unavailable; ordinary CI is not media proof")

    _, service, storage, _, project = _ready_project(monkeypatch, tmp_path)
    from app.video.cinematic_requests import AssembleMasterRequest

    source = storage.video_asset_path("4" * 32, "mp4")
    _encode_color(ffmpeg, source, "red", "160x90")
    request = AssembleMasterRequest(expected_revision=project.revision)
    first = service.assemble_project_master(project.id, request)
    assert first["status"] == "ready"
    cached = storage.video_asset_path(first["asset_id"], "mp4")
    assert _probe_frames(ffprobe, cached) == 48
    red = _decode_and_pixel(ffmpeg, cached)
    assert red[0] > red[2] + 60, tuple(red)
    red_sha = hashlib.sha256(cached.read_bytes()).hexdigest()
    assert first["sha256"] == red_sha

    replacement = tmp_path / "blue-master.mp4"
    _encode_color(ffmpeg, replacement, "blue", "854x480")
    assert _probe_frames(ffprobe, replacement) == 48
    blue = _decode_and_pixel(ffmpeg, replacement)
    assert blue[2] > blue[0] + 60, tuple(blue)
    blue_sha = hashlib.sha256(replacement.read_bytes()).hexdigest()
    assert blue_sha != red_sha

    # A cache hit hashes the original RED master. Another local writer
    # atomically replaces that pathname with a valid BLUE master immediately
    # after the digest is read. The returned SHA must describe bytes actually
    # available at the advertised asset path, or the hit must fail closed.
    original_digest = hashlib.file_digest
    swapped = []

    def swap_after_cached_digest(handle, algorithm):
        digest = original_digest(handle, algorithm)
        if Path(handle.name) == cached and not swapped:
            os.replace(replacement, cached)
            swapped.append(True)
        return digest

    monkeypatch.setattr(service.hashlib, "file_digest", swap_after_cached_digest)
    try:
        result = service.assemble_project_master(project.id, request)
    except (RuntimeError, ValueError) as exc:
        assert swapped, "The cached-master swap interleaving was not exercised"
        assert re.search(r"cache|asset|master|hash|changed|stale", str(exc), re.I), (
            "Only an explicit stale-output rejection is an acceptable failure"
        )
        return

    assert swapped, "The cached-master swap interleaving was not exercised"
    assert result["status"] == "ready"
    # A correct implementation may regenerate a fresh RED master at a NEW
    # asset ID rather than returning the now-swapped cached path. Both a
    # verified replacement and an explicit rejection satisfy the contract.
    advertised = storage.video_asset_path(result["asset_id"], "mp4")
    assert advertised.is_file()
    assert _probe_frames(ffprobe, advertised) == 48
    _decode_and_pixel(ffmpeg, advertised)
    actual_sha = hashlib.sha256(advertised.read_bytes()).hexdigest()
    assert result["sha256"] == actual_sha, (
        "Cached master returned READY with a stale SHA-256 while its advertised "
        "asset path served different, fully decodable MP4 bytes"
    )
