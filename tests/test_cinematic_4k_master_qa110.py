"""QA110: opt-in genuine 3840x2160 Character3D master assembly acceptance.

This uses only disposable local FFmpeg color clips. It verifies the *actual*
application assembly path at 2160p/24fps, not model inference, owner-PC
rendering, mobile hardware playback, or 600-second 4K performance.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("CINEMATIC_4K_MASTER_QA110") != "1",
    reason="opt-in genuine synthetic 4K application-level media acceptance only",
)


def _run(command: list[str], timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=True, capture_output=True, timeout=timeout)


def _mp4_box_types(path: Path) -> list[bytes]:
    """Read only ISO-BMFF top-level box headers; do not grep video payload."""
    boxes: list[bytes] = []
    size = path.stat().st_size
    with path.open("rb") as stream:
        offset = 0
        while offset < size:
            stream.seek(offset)
            header = stream.read(8)
            assert len(header) == 8, "Truncated MP4 box"
            length, kind = struct.unpack(">I4s", header)
            header_size = 8
            if length == 1:
                extended = stream.read(8)
                assert len(extended) == 8
                length = struct.unpack(">Q", extended)[0]
                header_size = 16
            elif length == 0:
                length = size - offset
            assert length >= header_size and offset + length <= size
            boxes.append(kind)
            offset += length
        assert offset == size
    return boxes


def _sample_rgb(path: Path, second: float) -> tuple[int, int, int]:
    raw = _run([
        "ffmpeg", "-nostdin", "-v", "error", "-xerror",
        "-ss", str(second), "-i", str(path), "-map", "0:v:0",
        "-frames:v", "1", "-vf", "scale=1:1:flags=area",
        "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
    ], timeout=120).stdout
    assert len(raw) == 3
    return tuple(raw)


def test_actual_character3d_4k_master_10s_24fps(monkeypatch, tmp_path: Path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.fail("Dedicated QA110 requires real FFmpeg and FFprobe")

    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    storage = importlib.import_module("app.video.storage")
    requests = importlib.import_module("app.video.cinematic_requests")

    asset_ids = []
    for index, color in enumerate(("red", "blue")):
        asset_id = f"{4110 + index:032x}"
        source = storage.video_asset_path(asset_id, "mp4")
        _run([
            "ffmpeg", "-nostdin", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=320x180:r=24:d=1",
            "-an", "-c:v", "mpeg4", "-q:v", "4", str(source),
        ], timeout=90)
        assert source.is_file() and source.stat().st_size > 1000
        asset_ids.append(asset_id)

    project = service.create_project(models.ProjectCreateRequest(
        title="QA110 synthetic 4K master only",
        master_prompt="Two synthetic colors, no model inference or owner media.",
        target_duration_seconds=10,
        delivery_fps=24, delivery_resolution="2160p", aspect_ratio="16:9",
    ))
    shots = [
        models.CinematicShot(
            shot_id=f"{4120 + i:032x}", ordinal=i + 1,
            title=f"Synthetic color shot {i + 1}",
            prompt="Disposable FFmpeg color source only.",
            duration_seconds=5.0,
        )
        for i in range(2)
    ]
    scene = models.CinematicScene(
        scene_id="a" * 32, ordinal=1, title="Two synthetic colors",
        target_duration_seconds=10, shots=shots,
    )
    project = service.update_project(
        project.id, models.ProjectUpdateRequest(
            expected_revision=1, scenes=[scene],
        ),
    )
    linked = []
    for shot, asset_id in zip(project.scenes[0].shots, asset_ids):
        record = storage.put_video_record("video_job", {
            "status": "succeeded", "project_id": project.id,
            "scene_id": scene.scene_id, "shot_id": shot.shot_id,
            "project_revision": project.revision,
            "asset_id": asset_id,
            "asset_url": f"/api/video/assets/{asset_id}.mp4",
        })
        linked.append(shot.model_copy(update={"latest_job_id": record["id"]}))
    project = service.update_project(
        project.id, models.ProjectUpdateRequest(
            expected_revision=2,
            scenes=[scene.model_copy(update={"shots": linked})],
        ),
    )

    result = service.assemble_project_master(
        project.id,
        requests.AssembleMasterRequest(expected_revision=project.revision),
    )
    assert result["status"] == "ready"
    assert result["actual_video_probe_verified"] is True
    assert result["source_shot_count"] == 2
    assert result["timeline_frames"] == 240
    assert result["timeline_seconds"] == pytest.approx(10.0)
    assert result["probe"]["width"] == 3840
    assert result["probe"]["height"] == 2160
    assert result["probe"]["frame_count"] == 240

    master = storage.video_asset_path(result["asset_id"], "mp4")
    with master.open("rb") as handle:
        assert hashlib.file_digest(handle, "sha256").hexdigest() == result["sha256"]
    boxes = _mp4_box_types(master)
    assert boxes[0] == b"ftyp"
    assert boxes.count(b"moov") == boxes.count(b"mdat") == 1
    assert boxes.index(b"moov") < boxes.index(b"mdat")

    probe = json.loads(_run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries",
        "stream=codec_name,pix_fmt,width,height,avg_frame_rate,nb_frames:"
        "format=duration",
        "-of", "json", str(master),
    ], timeout=120).stdout)
    video = probe["streams"][0]
    assert video["codec_name"] == "h264"
    assert video["pix_fmt"] == "yuv420p"
    assert (video["width"], video["height"]) == (3840, 2160)
    assert video["avg_frame_rate"] == "24/1"
    assert int(video["nb_frames"]) == 240
    assert float(probe["format"]["duration"]) == pytest.approx(10.0, abs=0.05)

    first = _sample_rgb(master, 2.5)
    second = _sample_rgb(master, 7.5)
    assert first[0] > first[2] + 50, first
    assert second[2] > second[0] + 50, second

    # Full 4K decode checks more than container headers or metadata.
    _run([
        "ffmpeg", "-nostdin", "-v", "error", "-xerror",
        "-i", str(master), "-map", "0:v:0", "-an", "-f", "null", "-",
    ], timeout=900)

    reused = service.assemble_project_master(
        project.id,
        requests.AssembleMasterRequest(expected_revision=project.revision),
    )
    assert reused["asset_id"] == result["asset_id"]
    assert reused["sha256"] == result["sha256"]
