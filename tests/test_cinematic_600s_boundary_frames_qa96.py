"""QA96: opt-in exact-cut frame checks on the real 600s synthetic master.

QA95 samples all shot centers, but a one-frame cut shift can preserve those
centers. This independent QA layer checks both sides of all 59 cut boundaries.
Synthetic FFmpeg input only; not owner footage, model inference or phone QA.
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path
import shutil
import subprocess

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("CINEMATIC_BOUNDARY_MEDIA_QA") != "1",
    reason="Exact-cut FFmpeg media acceptance is opt-in",
)


def _sample_rgb(path: Path, expression: str, *, timeout: int = 600):
    """Decode selected frames in presentation order; never trust probe alone."""
    result = subprocess.run(
        [
            "ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(path),
            "-an", "-vf", expression + ",scale=1:1:flags=area",
            "-vsync", "0", "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
        ],
        check=True, capture_output=True, timeout=timeout,
    )
    assert len(result.stdout) % 3 == 0
    return [
        tuple(result.stdout[i : i + 3])
        for i in range(0, len(result.stdout), 3)
    ]


def _near(actual, expected, tolerance=28):
    return all(abs(a - e) <= tolerance for a, e in zip(actual, expected))


def _assert_boundary_colors(path: Path, colors, *, frames_per_shot: int):
    """Check last frame of each shot and first frame of the next shot.

    For 60 shots of 240 frames, select n=239,240,479,480,...,14399.
    A center-only check cannot catch a one-frame boundary drift.
    """
    expression = (
        rf"select=eq(mod(n\,{frames_per_shot})\,{frames_per_shot - 1})"
        rf"+gt(n\,0)*eq(mod(n\,{frames_per_shot})\,0)"
    )
    samples = _sample_rgb(path, expression)
    assert len(samples) == 2 * len(colors) - 1, (
        f"Expected {2 * len(colors) - 1} boundary samples; got {len(samples)}"
    )
    for index, color in enumerate(colors):
        last_frame = samples[2 * index]
        assert _near(last_frame, color), (
            f"Shot {index + 1} last boundary frame {last_frame} != {color}"
        )
        if index + 1 < len(colors):
            next_first = samples[2 * index + 1]
            next_color = colors[index + 1]
            assert _near(next_first, next_color), (
                f"Shot {index + 2} first boundary frame {next_first} != {next_color}"
            )


def test_one_frame_shift_escapes_center_checks_but_fails_boundary_gate(tmp_path):
    """Real FFmpeg negative control: 25+23+24 frames, centers still correct."""
    if not shutil.which("ffmpeg"):
        pytest.fail("Dedicated QA requires ffmpeg")
    shifted = tmp_path / "one_frame_shift.mp4"
    cmd = ["ffmpeg", "-nostdin", "-y", "-hide_banner", "-loglevel", "error"]
    colors = [(255, 0, 0), (0, 128, 0), (0, 0, 255)]
    for name, count in (("red", 25), ("green", 23), ("blue", 24)):
        cmd += [
            "-f", "lavfi", "-i",
            f"color=c={name}:s=32x32:r=24:d={count / 24:.9f}",
        ]
    cmd += [
        "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
        "-map", "[v]", "-c:v", "mpeg4", str(shifted),
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=90)

    centers = _sample_rgb(
        shifted, r"select=eq(mod(n\,24)\,12)", timeout=90
    )
    assert len(centers) == 3
    assert all(_near(actual, expected) for actual, expected in zip(centers, colors))
    with pytest.raises(AssertionError, match="Shot 2 first boundary frame"):
        _assert_boundary_colors(shifted, colors, frames_per_shot=24)


def test_600_second_master_all_59_exact_cut_boundaries(monkeypatch, tmp_path):
    """Reuse QA95's actual app assembly; additionally verify 119 cut frames."""
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.fail("Dedicated QA requires ffmpeg and ffprobe")
    # Reuse the exact QA95 60-unique-source project setup, real FFmpeg assembly,
    # 14,400-frame full decode, all centers, hash and artifact-reuse checks.
    # No changes to QA95's independently owned test or production code.
    monkeypatch.setenv("CINEMATIC_ALL_SHOT_MEDIA_QA", "1")
    qa95 = importlib.import_module(
        "test_cinematic_600s_all_shot_continuity_qa95"
    )
    service = importlib.import_module("app.video.cinematic_service")
    storage = importlib.import_module("app.video.storage")
    original_assemble = service.assemble_project_master
    outputs = []

    def capture_assembly(*args, **kwargs):
        result = original_assemble(*args, **kwargs)
        outputs.append(result)
        return result

    monkeypatch.setattr(service, "assemble_project_master", capture_assembly)
    qa95.test_600_second_master_60_shots_real_ffmpeg(monkeypatch, tmp_path)
    assert len(outputs) == 2
    assert outputs[0]["asset_id"] == outputs[1]["asset_id"]
    master = storage.video_asset_path(outputs[0]["asset_id"], "mp4")
    assert master.is_file()

    expected_colors = []
    for index in range(60):
        code = (index * 13) % 64
        expected_colors.append((
            32 + 64 * (code // 16),
            32 + 64 * ((code // 4) % 4),
            32 + 64 * (code % 4),
        ))
    _assert_boundary_colors(master, expected_colors, frames_per_shot=240)
