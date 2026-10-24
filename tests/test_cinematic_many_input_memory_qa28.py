"""QA28: many-input FFmpeg memory/thread pressure after QA27's E2BIG workaround.

Strict tests are intentionally opt-in, so ordinary CI remains a smoke suite.
A service-command contract is expected RED until the lead bounds FFmpeg input
decoder and complex-filter threads. A separate real 700-input synthetic
FFmpeg encode verifies a feasible bounded-thread transport, not the service
integration, owner-PC performance, model inference, or mobile playback.
"""
from __future__ import annotations

from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from app.video.cinematic_filtergraph_transport_qa27 import (
    private_filtergraph_script_command,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("CINEMATIC_REQUIRE_MANY_INPUT_QA") != "1",
    reason="Strict many-input real-media QA28 runs in its dedicated workflow",
)

SHOT_COUNT = 700
FPS = 24
FRAMES_PER_SHOT = 12


def _tools() -> tuple[str, str]:
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.fail("Strict QA28 requires local FFmpeg and FFprobe")
    return ffmpeg, ffprobe


def test_service_many_shot_command_bounds_decoder_and_filter_threads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The current production command omits both thread bounds (expected RED).

    Captures the *actual* 700-shot service command without running FFmpeg.
    A later lead fix must still be separately checked for 700-source media.
    """
    service = importlib.import_module("app.video.cinematic_service")
    models = importlib.import_module("app.video.cinematic_models")
    requests = importlib.import_module("app.video.cinematic_requests")
    now = datetime.now(timezone.utc)
    source_id = "f" * 32
    (tmp_path / f"{source_id}.mp4").write_bytes(b"QA28 synthetic stub, NOT video")
    duration = SHOT_COUNT * 0.5
    shots = [
        models.CinematicShot(
            shot_id=f"{i + 1:032x}", ordinal=i + 1,
            title="Synthetic", prompt="No private owner media",
            duration_seconds=0.5,
        )
        for i in range(SHOT_COUNT)
    ]
    project = models.CinematicProject(
        id="d" * 32, revision=1, title="QA28 many-input contract",
        master_prompt="Synthetic only", target_duration_seconds=duration,
        delivery_fps=FPS, delivery_resolution="480p", aspect_ratio="16:9",
        scenes=[
            models.CinematicScene(
                scene_id="e" * 32, ordinal=1, title="Synthetic scene",
                target_duration_seconds=duration, shots=shots,
            )
        ],
        created_at=now, updated_at=now,
    )
    service.enforce_film_duration(project)
    monkeypatch.setattr(service, "get_project", lambda _id: project)
    monkeypatch.setattr(
        service, "_linked_shot_job",
        lambda _project, _scene, shot, **_kwargs: {
            "id": shot.shot_id, "asset_id": source_id,
        },
    )
    monkeypatch.setattr(service, "_job_has_local_render", lambda _job: True)
    monkeypatch.setattr(
        service, "video_asset_path",
        lambda identifier, ext: tmp_path / f"{identifier}.{ext}",
    )
    monkeypatch.setattr(service, "list_video_records", lambda _kind: [])
    observed: list[list[str]] = []

    def capture_without_encoding(command: list[str], **_kwargs) -> subprocess.CompletedProcess:
        observed.append(command)
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="")

    monkeypatch.setattr(service, "_run_master_ffmpeg", capture_without_encoding)
    with pytest.raises(RuntimeError, match="FFmpeg master assembly failed with exit code 2"):
        service.assemble_project_master(
            project.id, requests.AssembleMasterRequest(expected_revision=1),
        )
    assert len(observed) == 1
    command = observed[0]
    assert command.count("-i") == SHOT_COUNT
    # Required review contract: do not allow hundreds of auto-threaded
    # decoders and auto-threaded filtergraphs to exhaust a local owner PC.
    assert "-filter_complex_threads" in command, (
        "QA28: 700-input master command lacks a bounded complex-filter "
        "thread count; the 4 GiB local FFmpeg control was OOM-killed"
    )
    filter_threads = command.index("-filter_complex_threads")
    assert command[filter_threads + 1] == "1"
    input_indices = [i for i, arg in enumerate(command) if arg == "-i"]
    assert all(command[i - 2:i] == ["-threads", "1"] for i in input_indices), (
        "QA28: every source decoder needs an explicit bounded input-thread "
        "policy before -i; do not confuse output encoder threads with inputs"
    )


def test_genuine_700_input_synthetic_350_second_h264_master(
    tmp_path: Path,
) -> None:
    """Actually open 700 independent input streams and encode 8,400 frames.

    All 700 inputs reference the SAME locally generated 32x32 MP4; this
    exercises 700 FFmpeg input contexts, not 700 distinct owner shot assets.
    Small dimensions and explicitly bounded threads avoid runner OOM.
    """
    ffmpeg, ffprobe = _tools()
    source = tmp_path / "synthetic-shot.mp4"
    make_source = subprocess.run(
        [
            ffmpeg, "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=red:s=32x32:r=24:d=0.5",
            "-c:v", "libx264", "-threads", "1", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", str(source),
        ],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert make_source.returncode == 0, "Synthetic source generation failed"
    assert source.stat().st_size > 12

    filters = [
        (
            f"[{i}:v:0]fps=24,scale=32:32:force_original_aspect_ratio=decrease,"
            "pad=32:32:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p,"
            "tpad=stop_mode=clone:stop=12,trim=end_frame=12,"
            f"setpts=PTS-STARTPTS[v{i}]"
        )
        for i in range(SHOT_COUNT)
    ]
    filters.append(
        "".join(f"[v{i}]" for i in range(SHOT_COUNT))
        + f"concat=n={SHOT_COUNT}:v=1:a=0[v]"
    )
    graph = ";".join(filters)
    assert len(graph.encode("utf-8")) > 131072, "Must cover QA26 E2BIG scale"
    output = tmp_path / "synthetic-350s.mp4"
    command = [
        ffmpeg, "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
        "-filter_complex_threads", "1",
    ]
    for _ in range(SHOT_COUNT):
        command.extend(["-threads", "1", "-i", str(source)])
    command.extend([
        "-filter_complex", graph, "-map", "[v]", "-an",
        "-c:v", "libx264", "-threads", "1", "-preset", "ultrafast",
        "-crf", "30", "-r", str(FPS), "-fps_mode", "cfr",
        "-movflags", "+faststart", str(output),
    ])
    with private_filtergraph_script_command(command, directory=tmp_path) as safe:
        assert graph not in safe
        script = Path(safe[safe.index("-filter_complex_script") + 1])
        assert script.is_file()
        if os.name == "posix":
            assert script.stat().st_mode & 0o777 == 0o600
        encoded = subprocess.run(
            safe, capture_output=True, text=True, timeout=150, check=False,
        )
    assert encoded.returncode == 0, (
        f"Bounded-thread 700-input FFmpeg failed with exit code {encoded.returncode}"
    )
    assert not list(tmp_path.glob(".cinematic-filter-*"))
    assert output.is_file()
    probe = subprocess.run(
        [
            ffprobe, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,avg_frame_rate,nb_frames:format=duration",
            "-of", "json", str(output),
        ],
        capture_output=True, text=True, timeout=30, check=True,
    )
    data = json.loads(probe.stdout)
    stream = data["streams"][0]
    assert stream["codec_name"] == "h264"
    assert stream["avg_frame_rate"] == "24/1"
    assert int(stream["nb_frames"]) == SHOT_COUNT * FRAMES_PER_SHOT
    assert abs(float(data["format"]["duration"]) - 350.0) < 0.001
    decoded = subprocess.run(
        [ffmpeg, "-nostdin", "-v", "error", "-i", str(output), "-f", "null", "-"],
        capture_output=True, text=True, timeout=90, check=False,
    )
    assert decoded.returncode == 0, "Synthetic 350s master did not fully decode"
