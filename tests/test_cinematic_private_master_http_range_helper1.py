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


def test_private_master_overlapping_ranges_cannot_amplify_large_media(private_master):
    """Repeated overlapping byte ranges must not multiply a private film download.

    A single authenticated Range header can contain up to sixteen spans.
    Without canonicalization, sixteen full-film spans turn one request into
    sixteen complete reads/transfers; this is a bounded synthetic proof of
    a disproportionate large-master I/O and bandwidth cost.
    """
    client, auth, url, original = private_master
    repeated = ",".join(f"0-{len(original) - 1}" for _ in range(16))
    response = client.get(url, headers={**auth, "Range": f"bytes={repeated}"})
    assert response.status_code == 206, response.text[:160]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.content == original, (
        "Overlapping whole-file ranges must be coalesced, not retransmitted "
        "sixteen times in a multipart response."
    )
    assert response.headers["content-range"] == (
        f"bytes 0-{len(original) - 1}/{len(original)}"
    )
    assert int(response.headers["content-length"]) == len(original)


def test_private_master_disjoint_ranges_remain_multipart(private_master):
    """Normalization must not collapse genuinely disjoint mobile ranges."""
    client, auth, url, original = private_master
    response = client.get(url, headers={
        **auth, "Range": "bytes=0-127,512-639",
    })
    assert response.status_code == 206
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-type"].startswith("multipart/byteranges;")
    assert response.content.count(original[:128]) == 1
    assert response.content.count(original[512:640]) == 1
    assert int(response.headers["content-length"]) == len(response.content)


def test_private_master_if_range_rejects_same_size_mtime_atomic_replacement(
    private_master, tmp_path: Path,
):
    """Old If-Range must not splice a different real MP4 with the same stat ETag.

    An atomic replacement changes the inode but can preserve byte length and
    modification timestamp. This is a separate cross-request integrity case
    from an in-place rewrite of an already-open descriptor.
    """
    if os.name != "posix":
        pytest.skip("POSIX atomic-replacement identity regression")

    client, auth, url, original = private_master
    storage = importlib.import_module("app.video.storage")
    asset_id = url.rsplit("/", 1)[-1].removesuffix(".mp4")
    asset = storage.video_asset_path(asset_id, "mp4")
    ffmpeg, ffprobe = _media_tools()

    before = client.head(url, headers=auth)
    assert before.status_code == 200
    old_etag = before.headers["etag"]
    old_last_modified = before.headers["last-modified"]
    original_stat = asset.stat()

    replacement = tmp_path / "synthetic-blue-replacement.mp4"
    _run(ffmpeg, "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "color=c=blue:s=160x90:r=24:d=2",
         "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", str(replacement))
    blue = replacement.read_bytes()
    padding = len(original) - len(blue)
    assert padding >= 8, "Alternate real MP4 must fit the original byte length"
    # Valid ISO-BMFF trailing free box keeps the replacement fully decodable
    # while matching the original Content-Length exactly.
    changed = blue + padding.to_bytes(4, "big") + b"free" + bytes(padding - 8)
    replacement.write_bytes(changed)
    assert len(changed) == len(original)
    assert hashlib.sha256(changed).digest() != hashlib.sha256(original).digest()
    probe = json.loads(_run(
        ffprobe, "-v", "error", "-count_frames", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,nb_read_frames",
        "-of", "json", str(replacement),
    ).stdout)
    assert probe["streams"][0]["codec_name"] == "h264"
    assert int(probe["streams"][0]["nb_read_frames"]) == 48
    _run(ffmpeg, "-nostdin", "-v", "error", "-xerror", "-i",
         str(replacement), "-an", "-f", "null", "-")

    os.chmod(replacement, 0o600)
    os.utime(replacement, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    os.replace(replacement, asset)
    replaced_stat = asset.stat()
    assert replaced_stat.st_ino != original_stat.st_ino
    assert replaced_stat.st_size == original_stat.st_size
    assert replaced_stat.st_mtime_ns == original_stat.st_mtime_ns

    response = client.get(url, headers={
        **auth, "Range": "bytes=0-127", "If-Range": old_etag,
    })
    assert response.status_code == 200, (
        "An obsolete strong If-Range validator was reused after an atomic "
        "different-content MP4 replacement with identical size and mtime."
    )
    assert response.content == changed
    assert response.headers["etag"] != old_etag
    assert response.headers["cache-control"] == "no-store"

    # Last-Modified has only whole-second precision and cannot act as a
    # strong validator for quickly replaced private cinematic masters.
    dated = client.get(url, headers={
        **auth, "Range": "bytes=0-127", "If-Range": old_last_modified,
    })
    assert dated.status_code == 200, (
        "A stale If-Range HTTP date must not splice different master versions."
    )
    assert dated.content == changed
    assert dated.headers["cache-control"] == "no-store"

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


def test_private_master_tiny_range_snapshots_only_requested_bytes(
    private_master, monkeypatch,
):
    """A mobile 128-byte range must not copy a whole multi-GB film to disk.

    Snapshotting the entire source for every small range would create an
    authenticated I/O and temporary-disk amplification regression.
    """
    if os.name != "posix" or not hasattr(os, "pread"):
        pytest.skip("POSIX bounded range-snapshot contract")
    client, auth, url, original = private_master
    storage = importlib.import_module("app.video.storage")
    asset_id = url.rsplit("/", 1)[-1].removesuffix(".mp4")
    source = storage.video_asset_path(asset_id, "mp4")
    source_identity = (source.stat().st_dev, source.stat().st_ino)
    original_pread = os.pread
    source_bytes_requested = 0

    def count_source_reads(fd, count, offset):
        nonlocal source_bytes_requested
        stat_result = os.fstat(fd)
        if (stat_result.st_dev, stat_result.st_ino) == source_identity:
            source_bytes_requested += count
        return original_pread(fd, count, offset)

    monkeypatch.setattr(os, "pread", count_source_reads)
    try:
        response = client.get(url, headers={
            **auth, "Range": "bytes=0-127",
        })
    finally:
        monkeypatch.setattr(os, "pread", original_pread)
    assert response.status_code == 206
    assert response.content == original[:128]
    assert source_bytes_requested <= 128, (
        "A 128-byte mobile range copied the entire cinematic master to a "
        "temporary file, multiplying disk I/O and temporary storage."
    )


def test_private_master_concurrent_full_gets_have_bounded_snapshot_admission(
    private_master, monkeypatch,
):
    """No third authenticated full-film snapshot while two are in flight.

    The fixture is a real FFmpeg-assembled, FFprobed and fully decoded H.264
    master. The gate deliberately holds two existing snapshot operations
    without copying owner media or relying on wall-clock throughput.
    """
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, Lock

    client, auth, url, original = private_master
    router = importlib.import_module("app.video.router")
    snapshot = router._snapshot_private_asset
    release = Event()
    two_entered = Event()
    lock = Lock()
    entered = 0

    def held_snapshot(fd, opened, directory, ranges=None):
        nonlocal entered
        with lock:
            entered += 1
            ordinal = entered
            if entered >= 2:
                two_entered.set()
        if ordinal <= 2:
            if not release.wait(timeout=15):
                raise AssertionError("Timed out releasing synthetic snapshot gate")
        return snapshot(fd, opened, directory, ranges)

    monkeypatch.setattr(router, "_snapshot_private_asset", held_snapshot)
    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(client.get, url, headers=auth)
        second = pool.submit(client.get, url, headers=auth)
        try:
            assert two_entered.wait(timeout=8), (
                "Two synthetic authenticated master snapshots never entered"
            )
            third = pool.submit(client.get, url, headers=auth).result(timeout=8)
            assert third.status_code == 503, (
                "A third concurrent authenticated GET was admitted while "
                "two full-film snapshots were already occupying temporary "
                "storage; long-form masters can exhaust private asset disk."
            )
            assert third.headers.get("cache-control") == "no-store"
            assert third.content != original
        finally:
            release.set()
        for future in (first, second):
            response = future.result(timeout=15)
            assert response.status_code == 200
            assert response.content == original


@pytest.mark.parametrize(
    ("snapshot_failure", "expected_status"),
    [
        (OSError(28, "Synthetic disk-full during private snapshot"), 503),
        (ValueError("Synthetic source changed during private snapshot"), 409),
    ],
    ids=["disk-full", "source-changed"],
)
def test_private_master_snapshot_failure_is_noncacheable_and_recovers(
    private_master, monkeypatch, snapshot_failure, expected_status,
):
    """A failed private snapshot must not be cached or strand stream permits.

    The master is a real FFmpeg/FFprobe/full-decode H.264 assembled by the
    fixture. Inject one deterministic filesystem failure rather than filling
    the CI runner disk or touching owner footage; a subsequent GET must serve
    the same SHA-attested bytes after the failed snapshot releases its slot.
    """
    client, auth, url, original = private_master
    router = importlib.import_module("app.video.router")
    original_snapshot = router._snapshot_private_asset
    attempts = 0

    def fail_once(fd, opened, directory, ranges=None):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise snapshot_failure
        return original_snapshot(fd, opened, directory, ranges)

    monkeypatch.setattr(router, "_snapshot_private_asset", fail_once)
    failed = client.get(url, headers=auth)
    assert failed.status_code == expected_status, failed.text
    assert failed.content != original, "Failed snapshot served private media"
    assert failed.headers.get("cache-control") == "no-store", (
        "Transient private-master failures must never be reusable by a "
        "browser or intermediary cache, even under disk exhaustion."
    )
    if expected_status == 503:
        assert failed.headers.get("retry-after") == "1", (
            "A temporary private-snapshot capacity failure needs an "
            "explicit retry hint, like the concurrent-snapshot 503 path."
        )

    recovered = client.get(url, headers=auth)
    assert recovered.status_code == 200, recovered.text
    assert recovered.headers.get("cache-control") == "no-store"
    assert recovered.content == original, (
        "Snapshot failure leaked a stream permit or corrupted master bytes."
    )
    assert attempts == 2


def test_private_media_denials_and_missing_assets_are_never_cacheable(private_master):
    """A browser/proxy must not retain bearer-denial or missing-media responses.

    These requests exercise the *actual* private studio middleware and router
    against a real FFmpeg-assembled, fully decoded synthetic H.264 master.
    The 401 and 404 paths must be no-store, including HEAD and URL-token
    bypass attempts; no owner media, credentials, or paid service is involved.
    """
    client, auth, url, original = private_master
    missing_url = url.rsplit("/", 1)[0] + "/" + ("f" * 32) + ".mp4"
    assert len(original) > 2048

    for method in (client.get, client.head):
        for headers in ({}, {"Authorization": "Bearer wrong-token"}):
            response = method(url, headers=headers)
            assert response.status_code == 401
            assert response.headers.get("cache-control") == "no-store", (
                "Private media bearer-denial responses must never be cacheable"
            )
        token_query = method(url + "?token=synthetic-range-owner-token")
        assert token_query.status_code == 401
        assert token_query.headers.get("cache-control") == "no-store"

        missing = method(missing_url, headers=auth)
        assert missing.status_code == 404
        assert missing.headers.get("cache-control") == "no-store", (
            "Private media 404 responses must not be cached across asset recovery"
        )

    # The successful path remains authenticated and returns the genuine
    # original bytes, rather than a cached denial or placeholder.
    good = client.get(url, headers=auth)
    assert good.status_code == 200
    assert good.content == original
    assert good.headers["cache-control"] == "no-store"


def test_private_master_high_offset_ranges_use_compact_temporary_snapshots(
    private_master, monkeypatch,
):
    """A tiny tail Range must not create a film-sized logical temp file.

    The source is a genuine assembled, FFprobed, fully decoded H.264 master.
    Sparse seek-to-source-offset snapshots have a logical length as large as
    the full film even when only 128 bytes were read. On filesystems without
    reliable sparse allocation, a mobile tail request can exhaust disk.
    Assert temporary file length, not just the amount read from the source.
    """
    client, auth, url, original = private_master
    router = importlib.import_module("app.video.router")
    snapshot = router._snapshot_private_asset
    snapshot_lengths = []

    def inspect_snapshot(fd, opened, directory, ranges=None):
        result = snapshot(fd, opened, directory, ranges)
        temporary_fd = result[0] if isinstance(result, tuple) else result
        snapshot_lengths.append(os.fstat(temporary_fd).st_size)
        return result

    monkeypatch.setattr(router, "_snapshot_private_asset", inspect_snapshot)
    assert len(original) > 2048

    suffix = client.get(url, headers={**auth, "Range": "bytes=-128"})
    assert suffix.status_code == 206, suffix.text[:160]
    assert suffix.content == original[-128:]
    assert suffix.headers["cache-control"] == "no-store"
    assert snapshot_lengths[-1] <= 128, (
        "A 128-byte tail request produced a film-sized temporary file; "
        "snapshot ranges must be packed without sparse source offsets."
    )

    start = len(original) - 64
    disjoint = client.get(url, headers={
        **auth, "Range": f"bytes=0-63,{start}-{len(original) - 1}",
    })
    assert disjoint.status_code == 206
    assert disjoint.headers["content-type"].startswith("multipart/byteranges;")
    assert original[:64] in disjoint.content
    assert original[-64:] in disjoint.content
    assert snapshot_lengths[-1] <= 128, (
        "Disjoint mobile ranges must occupy only their actual snapshot bytes."
    )
