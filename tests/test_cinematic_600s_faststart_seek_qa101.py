"""QA101: opt-in 600-second MP4 faststart and random-seek acceptance.

Real synthetic FFmpeg sources through Character3D assembly; no owner media,
AI model inference, phone hardware, or live cloud generation.
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
    os.environ.get("CINEMATIC_FASTSTART_QA") != "1",
    reason="600s genuine synthetic faststart/seek QA is opt-in",
)


def _run(command: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=True, capture_output=True, timeout=timeout)


def _top_level_boxes(path: Path) -> list[tuple[bytes, int, int]]:
    """Walk top-level ISO BMFF boxes, never match 'moov' in arbitrary payload."""
    boxes = []
    with path.open("rb") as stream:
        size = path.stat().st_size
        offset = 0
        while offset < size:
            stream.seek(offset)
            header = stream.read(8)
            assert len(header) == 8, "Truncated top-level MP4 box"
            length, kind = struct.unpack(">I4s", header)
            header_size = 8
            if length == 1:
                extended = stream.read(8)
                assert len(extended) == 8, "Truncated extended box length"
                length = struct.unpack(">Q", extended)[0]
                header_size = 16
            elif length == 0:
                length = size - offset
            assert length >= header_size and offset + length <= size, (
                f"Invalid top-level MP4 box at offset {offset}"
            )
            boxes.append((kind, offset, length))
            offset += length
        assert offset == size
    return boxes


def _probe(path: Path) -> dict:
    return json.loads(_run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries",
        "stream=codec_name,pix_fmt,avg_frame_rate,nb_frames,width,height:"
        "format=duration",
        "-of", "json", str(path),
    ]).stdout)


def _seek_rgb(path: Path, second: float) -> tuple[int, int, int]:
    # Input-side seek exercises MP4 index/random-access behavior rather than
    # decoding from frame zero and then selecting an output-side frame.
    raw = _run([
        "ffmpeg", "-nostdin", "-v", "error", "-xerror",
        "-ss", str(second), "-i", str(path), "-map", "0:v:0",
        "-frames:v", "1", "-vf", "scale=1:1:flags=area",
        "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
    ], timeout=120).stdout
    assert len(raw) == 3, f"No single decoded frame at {second}s"
    return tuple(raw)


def _assert_color(actual: tuple[int, int, int], expected: tuple[int, int, int]):
    assert all(abs(a - b) <= 28 for a, b in zip(actual, expected)), (
        f"Decoded seek color {actual} differs from {expected}"
    )


def test_box_parser_detects_nonfaststart_negative_control(tmp_path: Path):
    """A real MP4 without +faststart must fail the master-layout predicate."""
    if not shutil.which("ffmpeg"):
        pytest.fail("Opt-in real-media QA requires FFmpeg")
    default = tmp_path / "tail-moov.mp4"
    _run([
        "ffmpeg", "-nostdin", "-y", "-v", "error",
        "-f", "lavfi", "-i", "color=c=red:s=160x90:r=24:d=1",
        "-c:v", "mpeg4", "-q:v", "4", str(default),
    ], timeout=90)
    kinds = [kind for kind, _, _ in _top_level_boxes(default)]
    assert b"mdat" in kinds and b"moov" in kinds
    assert kinds.index(b"mdat") < kinds.index(b"moov"), (
        "Negative control unexpectedly has faststart layout"
    )


def test_600s_character3d_master_faststart_and_indexed_seek(
    monkeypatch, tmp_path: Path,
):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.fail("Opt-in real-media QA requires FFmpeg and FFprobe")
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    storage = importlib.import_module("app.video.storage")
    requests = importlib.import_module("app.video.cinematic_requests")

    asset_ids = []
    for index, color in enumerate(("red", "blue")):
        asset_id = f"{2100 + index:032x}"
        source = storage.video_asset_path(asset_id, "mp4")
        _run([
            "ffmpeg", "-nostdin", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=160x90:r=24:d=1",
            "-an", "-c:v", "mpeg4", "-q:v", "4", str(source),
        ], timeout=90)
        asset_ids.append(asset_id)

    project = service.create_project(models.ProjectCreateRequest(
        title="QA101 600s indexed mobile-readiness synthetic master",
        master_prompt="Locally generated color only, no private content.",
        target_duration_seconds=600, delivery_fps=24,
        delivery_resolution="480p", aspect_ratio="16:9",
    ))
    shots = [
        models.CinematicShot(
            shot_id=f"{2200 + i:032x}", ordinal=i + 1,
            title=f"Synthetic shot {i + 1}",
            prompt="Synthetic source frame clone only.",
            duration_seconds=30,
        )
        for i in range(20)
    ]
    scene = models.CinematicScene(
        scene_id="8" * 32, ordinal=1, title="Seek midpoint transition",
        target_duration_seconds=600, shots=shots,
    )
    project = service.update_project(project.id, models.ProjectUpdateRequest(
        expected_revision=1, scenes=[scene],
    ))
    linked = []
    for i, shot in enumerate(project.scenes[0].shots):
        asset_id = asset_ids[0 if i < 10 else 1]
        job = storage.put_video_record("video_job", {
            "status": "succeeded", "project_id": project.id,
            "scene_id": scene.scene_id, "shot_id": shot.shot_id,
            "project_revision": project.revision,
            "asset_id": asset_id,
            "asset_url": f"/api/video/assets/{asset_id}.mp4",
        })
        linked.append(shot.model_copy(update={"latest_job_id": job["id"]}))
    project = service.update_project(project.id, models.ProjectUpdateRequest(
        expected_revision=2,
        scenes=[scene.model_copy(update={"shots": linked})],
    ))

    result = service.assemble_project_master(
        project.id, requests.AssembleMasterRequest(expected_revision=project.revision),
    )
    assert result["status"] == "ready"
    assert result["timeline_frames"] == 14_400
    assert result["probe"]["frame_count"] == 14_400
    assert result["probe"]["duration_seconds"] == pytest.approx(600, abs=0.05)
    master = storage.video_asset_path(result["asset_id"], "mp4")
    with master.open("rb") as handle:
        assert hashlib.file_digest(handle, "sha256").hexdigest() == result["sha256"]

    boxes = _top_level_boxes(master)
    kinds = [kind for kind, _, _ in boxes]
    assert kinds[0] == b"ftyp"
    assert kinds.count(b"moov") == kinds.count(b"mdat") == 1
    assert kinds.index(b"moov") < kinds.index(b"mdat"), (
        "Master's MP4 index is after the media payload: progressive playback "
        "may need the entire download before seeking"
    )
    probe = _probe(master)
    video = probe["streams"][0]
    assert video["codec_name"] == "h264"
    assert video["pix_fmt"] == "yuv420p"
    assert video["avg_frame_rate"] == "24/1"
    assert int(video["nb_frames"]) == 14_400
    assert float(probe["format"]["duration"]) == pytest.approx(600, abs=0.05)

    # Seek at the beginning, before/after the 300s cut, and near the end.
    for second, expected in (
        (0.5, (255, 0, 0)),
        (299.5, (255, 0, 0)),
        (300.5, (0, 0, 255)),
        (599.5, (0, 0, 255)),
    ):
        _assert_color(_seek_rgb(master, second), expected)

    _run([
        "ffmpeg", "-nostdin", "-v", "error", "-xerror",
        "-i", str(master), "-an", "-f", "null", "-",
    ], timeout=600)
    reused = service.assemble_project_master(
        project.id, requests.AssembleMasterRequest(expected_revision=project.revision),
    )
    assert reused["asset_id"] == result["asset_id"]
    assert reused["sha256"] == result["sha256"]
