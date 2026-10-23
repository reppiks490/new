"""Strict cached-master integrity: a matching SHA is not full-decode proof.

Uses only synthetic, CPU-encoded FFmpeg media. A previously verified master is
corrupted *after* creation; the stored SHA is updated to match the damaged
bytes while stale ffprobe metadata remains. This models a hash-consistent
legacy/stale cache record, not a forged cryptographic hash or owner footage.
The cache must not publish an undecodable MP4 as ready.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from test_cinematic_assembly_queue import _ready_project


def _media_tools():
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        if os.getenv("CINEMATIC_REQUIRE_REAL_MEDIA") == "1":
            pytest.fail("Strict cached-master QA requires real FFmpeg and FFprobe")
        pytest.skip("FFmpeg/FFprobe absent; ordinary CI is not real-media proof")
    return ffmpeg, ffprobe


def _decode(ffmpeg: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [ffmpeg, "-nostdin", "-v", "error", "-xerror", "-i", str(path),
         "-map", "0:v:0", "-an", "-f", "null", "-"],
        capture_output=True, timeout=90, check=False,
    )


def _probe(ffprobe: str, path: Path) -> dict | None:
    completed = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name,avg_frame_rate,nb_frames",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=60, check=False,
    )
    return json.loads(completed.stdout) if completed.returncode == 0 else None


def test_hash_consistent_but_undecodable_cached_master_is_not_reused(
    monkeypatch, tmp_path: Path,
):
    ffmpeg, ffprobe = _media_tools()
    _, service, storage, _, project = _ready_project(monkeypatch, tmp_path)
    from app.video.cinematic_requests import AssembleMasterRequest

    source = storage.video_asset_path("4" * 32, "mp4")
    subprocess.run(
        [ffmpeg, "-nostdin", "-y", "-v", "error", "-f", "lavfi",
         "-i", "testsrc2=size=160x90:rate=24:duration=2",
         "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", str(source)],
        capture_output=True, timeout=90, check=True,
    )
    request = AssembleMasterRequest(expected_revision=project.revision)
    original = service.assemble_project_master(project.id, request)
    original_path = storage.video_asset_path(original["asset_id"], "mp4")
    assert original["status"] == "ready"
    assert _decode(ffmpeg, original_path).returncode == 0
    original_probe = _probe(ffprobe, original_path)
    assert original_probe and int(original_probe["streams"][0]["nb_frames"]) == 48

    full_bytes = original_path.read_bytes()
    assert b"moov" in full_bytes[:8192], "Fixture requires faststart metadata"
    damaged = False
    for fraction in (0.75, 0.65, 0.55):
        original_path.write_bytes(full_bytes[:int(len(full_bytes) * fraction)])
        info = _probe(ffprobe, original_path)
        if (info and info.get("streams")
                and int(info["streams"][0].get("nb_frames", 0)) == 48
                and info["streams"][0].get("codec_name") == "h264"
                and _decode(ffmpeg, original_path).returncode != 0):
            damaged = True
            break
    assert damaged, "Fixture must retain ffprobe frame metadata but fail full decode"

    # This is *not* a SHA mismatch: the record's SHA matches the corrupt bytes.
    # The stale 'probe_metadata_verified' flag is insufficient media evidence.
    stale = dict(original)
    stale["sha256"] = hashlib.sha256(original_path.read_bytes()).hexdigest()
    stale["size_bytes"] = original_path.stat().st_size
    assert stale["probe"]["probe_metadata_verified"] is True
    assert stale["probe"]["full_decode_verified"] is False
    storage.put_video_record("video_master", stale, identifier=original["id"])

    try:
        candidate = service.assemble_project_master(project.id, request)
    except (RuntimeError, ValueError):
        persisted = storage.get_video_record("video_master", original["id"])
        assert persisted.get("status") != "ready", (
            "Undecodable cached master remained published as ready after rejection"
        )
        return

    if candidate.get("status") == "ready":
        path = storage.video_asset_path(candidate["asset_id"], "mp4")
        assert _decode(ffmpeg, path).returncode == 0, (
            "Hash-consistent but undecodable cached MP4 was returned as ready"
        )
        assert candidate["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    else:
        assert candidate.get("status") != "ready"
