"""Helper 1: real assembled MP4 private HTTP byte-range and HEAD acceptance.

An iPhone/mobile preview can request partial media bytes and metadata before
streaming. The private asset endpoint must authorize every request method,
preserve no-store, and serve the exact bytes of a fully decodable master.
Only synthetic FFmpeg media is used; no owner footage or paid generation.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest


def _media_tools():
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        if os.getenv("CINEMATIC_REQUIRE_REAL_MEDIA") == "1":
            pytest.fail("Strict mobile HTTP media QA requires FFmpeg and FFprobe")
        pytest.skip("FFmpeg/FFprobe unavailable in ordinary CI")
    return ffmpeg, ffprobe


def _run(*argv):
    return subprocess.run(argv, check=True, capture_output=True, timeout=120)


@pytest.fixture
def private_master(monkeypatch, tmp_path: Path):
    ffmpeg, ffprobe = _media_tools()
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("CHARACTER3D_STUDIO_TOKEN", "synthetic-range-owner-token")
    monkeypatch.setenv("CHARACTER3D_STUDIO_ORIGINS", "")

    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    storage = importlib.import_module("app.video.storage")

    project = service.create_project(models.ProjectCreateRequest(
        title="Synthetic private range QA", master_prompt="No owner footage",
        target_duration_seconds=10, delivery_fps=24,
        delivery_resolution="480p", aspect_ratio="16:9",
    ))
    shot = models.CinematicShot(
        shot_id="3" * 32, ordinal=1, title="Synthetic red",
        prompt="Generated test pattern only", duration_seconds=2,
    )
    scene = models.CinematicScene(
        scene_id="2" * 32, ordinal=1, title="Synthetic scene",
        target_duration_seconds=2, shots=[shot],
    )
    project = service.update_project(
        project.id, models.ProjectUpdateRequest(expected_revision=1, scenes=[scene]),
    )
    source_id = "4" * 32
    source = storage.video_asset_path(source_id, "mp4")
    _run(ffmpeg, "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "color=c=red:s=160x90:r=24:d=2",
         "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", str(source))
    _run(ffmpeg, "-nostdin", "-v", "error", "-xerror", "-i", str(source),
         "-an", "-f", "null", "-")

    job = storage.put_video_record("video_job", {
        "status": "succeeded", "project_id": project.id,
        "scene_id": scene.scene_id, "shot_id": shot.shot_id,
        "asset_id": source_id, "project_revision": project.revision,
    })
    linked = shot.model_copy(update={
        "latest_job_id": job["id"], "latest_rendered_project_revision": 2,
    })
    project = service.update_project(
        project.id, models.ProjectUpdateRequest(
            expected_revision=2,
            scenes=[scene.model_copy(update={"shots": [linked]})],
        ),
    )
    assert service.project_render_status(project.id)["ready_for_assembly"]

    for module in ("app.studio.server", "app.video.router"):
        sys.modules.pop(module, None)
    server = importlib.import_module("app.studio.server")
    auth = {"Authorization": "Bearer synthetic-range-owner-token"}
    with TestClient(server.app) as client:
        response = client.post(
            f"/api/video/projects/{project.id}/assemble",
            json={"expected_revision": project.revision}, headers=auth,
        )
        assert response.status_code == 200, response.text
        master = response.json()
        assert master["status"] == "ready"
        assert master["actual_video_probe_verified"] is True
        assert master["probe"]["probe_metadata_verified"] is True
        asset = storage.video_asset_path(master["asset_id"], "mp4")
        payload = asset.read_bytes()
        assert len(payload) > 2048
        assert hashlib.sha256(payload).hexdigest() == master["sha256"]
        probe = json.loads(_run(
            ffprobe, "-v", "error", "-count_frames", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,nb_read_frames",
            "-of", "json", str(asset),
        ).stdout)
        assert probe["streams"][0]["codec_name"] == "h264"
        assert int(probe["streams"][0]["nb_read_frames"]) == 48
        _run(ffmpeg, "-nostdin", "-v", "error", "-xerror", "-i", str(asset),
             "-an", "-f", "null", "-")
        yield client, auth, master["asset_url"], payload


def test_private_master_http_ranges_are_authorized_exact_and_noncacheable(private_master):
    client, auth, url, original = private_master
    for unauthorized in ({}, {"Authorization": "Bearer wrong-token"}):
        denied = client.get(url, headers={**unauthorized, "Range": "bytes=0-1023"})
        assert denied.status_code == 401
        assert denied.content != original[:1024]
    assert client.get(
        url + "?token=synthetic-range-owner-token",
        headers={"Range": "bytes=0-1023"},
    ).status_code == 401

    first = client.get(url, headers={**auth, "Range": "bytes=0-1023"})
    rest = client.get(url, headers={**auth, "Range": "bytes=1024-"})
    for response in (first, rest):
        assert response.status_code == 206, response.text[:120]
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["accept-ranges"] == "bytes"
        assert response.headers["content-type"].startswith("video/mp4")
    assert first.headers["content-range"] == f"bytes 0-1023/{len(original)}"
    assert rest.headers["content-range"] == f"bytes 1024-{len(original)-1}/{len(original)}"
    reconstructed = first.content + rest.content
    assert reconstructed == original
    assert hashlib.sha256(reconstructed).hexdigest() == hashlib.sha256(original).hexdigest()

    suffix = client.get(url, headers={**auth, "Range": "bytes=-256"})
    assert suffix.status_code == 206
    assert suffix.headers["cache-control"] == "no-store"
    assert suffix.content == original[-256:]


def test_private_master_head_preflight_has_metadata_without_media_body(private_master):
    client, auth, url, original = private_master
    assert client.head(url).status_code == 401
    assert client.head(url, headers={"Authorization": "Bearer wrong-token"}).status_code == 401
    assert client.head(url + "?token=synthetic-range-owner-token").status_code == 401

    # HEAD must not return the MP4 body; it lets a mobile preview determine
    # size/type and byte-range support without fetching the entire private film.
    response = client.head(url, headers=auth)
    assert response.status_code == 200, (
        f"Authenticated private master HEAD returned {response.status_code}; "
        "mobile metadata preflight cannot inspect the protected MP4."
    )
    assert response.content == b""
    assert int(response.headers["content-length"]) == len(original)
    assert response.headers["content-type"].startswith("video/mp4")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["accept-ranges"] == "bytes"


def test_private_master_stream_must_not_serve_inplace_rewritten_inode(
    private_master, monkeypatch, tmp_path: Path,
):
    """A pinned descriptor is not a byte snapshot if its inode is rewritten.

    This deterministic race uses two genuine, fully decoded synthetic H.264
    MP4s. A local same-user writer overwrites the already-opened master inode
    just before its first pread. The authenticated response must never return
    200 with bytes different from the original SHA-attested master.
    This tests a local integrity boundary, not remote exploitability.
    """
    if os.name != "posix" or not hasattr(os, "pread"):
        pytest.skip("POSIX descriptor-stream mutation contract")

    client, auth, url, original = private_master
    storage = importlib.import_module("app.video.storage")
    asset_id = url.rsplit("/", 1)[-1].removesuffix(".mp4")
    asset = storage.video_asset_path(asset_id, "mp4")
    ffmpeg, ffprobe = _media_tools()

    blue = tmp_path / "synthetic-blue.mp4"
    _run(ffmpeg, "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "color=c=blue:s=160x90:r=24:d=2",
         "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", str(blue))
    blue_bytes = blue.read_bytes()
    padding = len(original) - len(blue_bytes)
    assert padding >= 8, "Synthetic alternate MP4 must fit original inode size"
    # A valid trailing ISO-BMFF free box makes the BLUE video exactly the
    # original master's size, avoiding any short-read/truncation confounder.
    rewritten = (
        blue_bytes + padding.to_bytes(4, "big") + b"free"
        + bytes(padding - 8)
    )
    assert len(rewritten) == len(original)
    assert hashlib.sha256(rewritten).digest() != hashlib.sha256(original).digest()
    blue_padded = tmp_path / "synthetic-blue-same-length.mp4"
    blue_padded.write_bytes(rewritten)
    probe = json.loads(_run(
        ffprobe, "-v", "error", "-count_frames", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,nb_read_frames",
        "-of", "json", str(blue_padded),
    ).stdout)
    assert probe["streams"][0]["codec_name"] == "h264"
    assert int(probe["streams"][0]["nb_read_frames"]) == 48
    _run(ffmpeg, "-nostdin", "-v", "error", "-xerror", "-i",
         str(blue_padded), "-an", "-f", "null", "-")

    opened_identity = (asset.stat().st_dev, asset.stat().st_ino)
    real_pread = os.pread
    overwritten = False

    def overwrite_after_open_before_first_read(fd, count, offset):
        nonlocal overwritten
        opened = os.fstat(fd)
        if not overwritten and (opened.st_dev, opened.st_ino) == opened_identity:
            overwritten = True
            # In-place write preserves device/inode and file length. A
            # no-follow open and final lstat cannot detect this by identity.
            with asset.open("r+b") as stream:
                stream.write(rewritten)
                stream.flush()
                os.fsync(stream.fileno())
        return real_pread(fd, count, offset)

    monkeypatch.setattr(os, "pread", overwrite_after_open_before_first_read)
    try:
        response = client.get(url, headers=auth)
    finally:
        monkeypatch.setattr(os, "pread", real_pread)

    assert overwritten, "The test did not reach the pinned descriptor read"
    assert response.status_code != 200 or response.content == original, (
        "Authenticated 200 response served different synthetic H.264 bytes "
        "after the already-opened master inode was rewritten in place; "
        "descriptor pinning alone does not pin content integrity."
    )
