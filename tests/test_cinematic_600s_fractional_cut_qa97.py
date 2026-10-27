"""QA97: opt-in genuine FFmpeg acceptance of fractional cuts in a 600s master.

60 independently encoded synthetic color sources; no owner media, model
inference, phone hardware, cloud generation or production changes.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import hashlib
import importlib
import os
from pathlib import Path
import shutil
import subprocess

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("CINEMATIC_FRACTIONAL_MEDIA_QA") != "1",
    reason="600s fractional-cut FFmpeg acceptance is opt-in",
)

DURATIONS = ("10.02", "10.02", "9.96") * 20
FPS = 24


def _expected_ends():
    """Independent cumulative Decimal frame oracle; do not use app preflight."""
    elapsed = Decimal(0)
    ends = []
    for duration in DURATIONS:
        elapsed += Decimal(duration)
        ends.append(int((elapsed * FPS).to_integral_value(rounding=ROUND_HALF_UP)))
    return ends


def test_fractional_cut_oracle_exposes_independent_rounding_drift():
    ends = _expected_ends()
    lengths = [end - (ends[index - 1] if index else 0)
               for index, end in enumerate(ends)]
    independently_rounded = sum(
        int((Decimal(duration) * FPS).to_integral_value(rounding=ROUND_HALF_UP))
        for duration in DURATIONS
    )
    assert len(ends) == 60
    assert ends[:6] == [240, 481, 720, 960, 1201, 1440]
    assert set(lengths) == {239, 240, 241}
    assert ends[-1] == sum(lengths) == 14_400
    assert independently_rounded == 14_380  # A real 20-frame test blind spot.


def _color(index: int):
    code = (index * 13) % 64
    return (32 + 64 * (code // 16),
            32 + 64 * ((code // 4) % 4),
            32 + 64 * (code % 4))



def _balanced_selector(positions):
    """Bound FFmpeg expression depth; 179 left-associative '+' terms fail."""
    terms = [f"eq(n\\,{frame})" for frame in positions]
    assert terms
    while len(terms) > 1:
        terms = [
            f"max({terms[index]}\\,{terms[index + 1]})"
            if index + 1 < len(terms) else terms[index]
            for index in range(0, len(terms), 2)
        ]
    return "select=" + terms[0]


def test_balanced_selector_accepts_179_terms_with_real_ffmpeg(tmp_path):
    """Small synthetic negative-control for FFmpeg's expression-depth ceiling."""
    if not shutil.which("ffmpeg"):
        pytest.fail("Dedicated media QA requires ffmpeg")
    sample = tmp_path / "selector-control.mp4"
    subprocess.run([
        "ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi",
        "-i", "color=c=red:s=16x16:r=24:d=2",
        "-c:v", "mpeg4", str(sample),
    ], check=True, capture_output=True, timeout=90)
    decoded = subprocess.run([
        "ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(sample),
        "-an", "-vf", _balanced_selector(range(179)),
        "-vsync", "0", "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
    ], check=True, capture_output=True, timeout=90).stdout
    assert len(decoded) == 48 * 16 * 16 * 3

def test_600s_fractional_cut_application_assembly(monkeypatch, tmp_path: Path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.fail("Dedicated media QA requires ffmpeg and ffprobe")
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    storage = importlib.import_module("app.video.storage")
    requests = importlib.import_module("app.video.cinematic_requests")
    editing = importlib.import_module("app.video.cinematic_editing")

    assets, digests = [], set()
    for index in range(60):
        asset_id = f"{100 + index:032x}"
        rgb = _color(index)
        color = "0x" + "".join(f"{channel:02x}" for channel in rgb)
        path = storage.video_asset_path(asset_id, "mp4")
        subprocess.run([
            "ffmpeg", "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=160x90:r=24:d=1",
            "-an", "-c:v", "mpeg4", "-q:v", "4", str(path),
        ], check=True, capture_output=True, timeout=90)
        with path.open("rb") as handle:
            digests.add(hashlib.file_digest(handle, "sha256").hexdigest())
        assets.append(asset_id)
    assert len(digests) == len(set(assets)) == 60

    project = service.create_project(models.ProjectCreateRequest(
        title="QA97 600s fractional-cut synthetic film",
        master_prompt="Local synthetic color sources only; no AI inference.",
        target_duration_seconds=600,
        delivery_fps=FPS,
        delivery_resolution="480p",
        aspect_ratio="16:9",
    ))
    shots = [
        models.CinematicShot(
            shot_id=f"{1000 + index:032x}", ordinal=index + 1,
            title=f"Synthetic fractional shot {index + 1}",
            prompt="Local synthetic color frames only.",
            duration_seconds=float(duration),
        )
        for index, duration in enumerate(DURATIONS)
    ]
    scene = models.CinematicScene(
        scene_id="2" * 32, ordinal=1, title="Fractional timeline",
        target_duration_seconds=600, shots=shots,
    )
    project = service.update_project(project.id, models.ProjectUpdateRequest(
        expected_revision=1, scenes=[scene],
    ))
    linked = []
    for index, shot in enumerate(project.scenes[0].shots):
        asset_id = assets[index]
        record = storage.put_video_record("video_job", {
            "status": "succeeded",
            "project_id": project.id,
            "scene_id": scene.scene_id,
            "shot_id": shot.shot_id,
            "project_revision": project.revision,
            "asset_id": asset_id,
            "asset_url": f"/api/video/assets/{asset_id}.mp4",
        })
        linked.append(shot.model_copy(update={"latest_job_id": record["id"]}))
    project = service.update_project(project.id, models.ProjectUpdateRequest(
        expected_revision=2,
        scenes=[scene.model_copy(update={"shots": linked})],
    ))

    ends = _expected_ends()
    timeline = editing.preflight_editorial_timeline(project)
    assert [clip.end_frame for clip in timeline.clips] == ends
    assert timeline.actual_frames == timeline.target_frames == 14_400
    assert timeline.frame_difference == 0

    result = service.assemble_project_master(
        project.id,
        requests.AssembleMasterRequest(expected_revision=project.revision),
    )
    assert result["status"] == "ready"
    assert result["source_shot_count"] == 60
    assert result["timeline_frames"] == 14_400
    assert result["probe"]["codec"] == "h264"
    assert result["probe"]["frame_count"] == 14_400
    assert result["probe"]["duration_seconds"] == pytest.approx(600, abs=0.05)

    master = storage.video_asset_path(result["asset_id"], "mp4")
    with master.open("rb") as handle:
        assert hashlib.file_digest(handle, "sha256").hexdigest() == result["sha256"]
    subprocess.run([
        "ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(master),
        "-an", "-f", "null", "-",
    ], check=True, capture_output=True, timeout=600)

    # Every center, final frame, and first frame after each of 59 cuts.
    expected = {}
    start = 0
    for index, end in enumerate(ends):
        color = _color(index)
        expected[start + (end - start) // 2] = color
        expected[end - 1] = color
        if index:
            expected[start] = color
        start = end
    assert len(expected) == 179
    positions = sorted(expected)
    selector = _balanced_selector(positions)
    decoded = subprocess.run([
        "ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(master),
        "-an", "-vf", selector + ",scale=1:1:flags=area",
        "-vsync", "0", "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
    ], check=True, capture_output=True, timeout=600).stdout
    assert len(decoded) == 3 * len(positions), (
        f"Expected {len(positions)} selected frames, got {len(decoded) // 3}"
    )
    for index, frame in enumerate(positions):
        actual = decoded[index * 3:index * 3 + 3]
        assert all(abs(a - b) <= 28 for a, b in zip(actual, expected[frame])), (
            f"Frame {frame} color {tuple(actual)} != {expected[frame]}"
        )

    reused = service.assemble_project_master(
        project.id,
        requests.AssembleMasterRequest(expected_revision=project.revision),
    )
    assert reused["asset_id"] == result["asset_id"]
    assert reused["sha256"] == result["sha256"]
