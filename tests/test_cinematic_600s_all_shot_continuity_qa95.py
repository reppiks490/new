"""QA95: opt-in 600-second 60-distinct-source all-shot continuity acceptance.

Exercises the actual cinematic assembly path with 60 distinct ordered ten-second
synthetic color clips, inspecting all 60 shot centers with real FFmpeg/FFprobe;
no model inference, owner media, mobile hardware, or paid services are involved.

The environment gate prevents this long-running acceptance from silently
inflating every general CI run. Dedicated QA93 workflow explicitly enables it.
"""
from __future__ import annotations

import hashlib
import importlib
import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(
    os.environ.get("CINEMATIC_ALL_SHOT_MEDIA_QA") != "1",
    reason="600-second all-shot synthetic FFmpeg acceptance is opt-in",
)
def test_600_second_master_60_shots_real_ffmpeg(monkeypatch, tmp_path: Path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.fail("Dedicated long-form media acceptance requires ffmpeg and ffprobe")
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))

    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    storage = importlib.import_module("app.video.storage")
    requests = importlib.import_module("app.video.cinematic_requests")

    # 60 different source bytes, each a separated point in a 4x4x4 RGB
    # lattice (64 channel units apart). Multiplication by 13 permutes the
    # positions to make adjacent shots distinct.
    assets = []
    colors = []
    hashes = set()
    for index in range(60):
        code = (index * 13) % 64
        rgb = (
            32 + 64 * (code // 16),
            32 + 64 * ((code // 4) % 4),
            32 + 64 * (code % 4),
        )
        colors.append(rgb)
        asset_id = f"{100 + index:032x}"
        path = storage.video_asset_path(asset_id, "mp4")
        color = "0x" + "".join(f"{channel:02x}" for channel in rgb)
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", f"color=c={color}:s=160x90:r=24:d=1",
                "-an", "-c:v", "mpeg4", "-q:v", "4", str(path),
            ],
            check=True, capture_output=True, text=True, timeout=90,
        )
        assert path.is_file() and path.stat().st_size > 1000
        with path.open("rb") as handle:
            hashes.add(hashlib.file_digest(handle, "sha256").hexdigest())
        assets.append(asset_id)
    assert len(set(colors)) == len(hashes) == len(assets) == 60

    project = service.create_project(
        models.ProjectCreateRequest(
            title="QA95 synthetic 600-second 60-distinct-shot film",
            master_prompt="Synthetic distinct colors for all-shot continuity QA only.",
            target_duration_seconds=600,
            delivery_fps=24,
            delivery_resolution="480p",
            aspect_ratio="16:9",
        )
    )
    shots = [
        models.CinematicShot(
            shot_id=f"{1000 + index:032x}",
            ordinal=index + 1,
            title=f"Synthetic shot {index + 1}",
            prompt="Local color frames, no inference.",
            duration_seconds=10.0,
        )
        for index in range(60)
    ]
    scene = models.CinematicScene(
        scene_id="2" * 32, ordinal=1, title="Long-form sequence",
        target_duration_seconds=600, shots=shots,
    )
    project = service.update_project(
        project.id,
        models.ProjectUpdateRequest(expected_revision=1, scenes=[scene]),
    )
    linked = []
    for index, shot in enumerate(project.scenes[0].shots):
        asset_id = assets[index]
        record = storage.put_video_record(
            "video_job", {
                "status": "succeeded",
                "project_id": project.id,
                "scene_id": scene.scene_id,
                "shot_id": shot.shot_id,
                "project_revision": project.revision,
                "asset_id": asset_id,
                "asset_url": f"/api/video/assets/{asset_id}.mp4",
            },
        )
        linked.append(shot.model_copy(update={"latest_job_id": record["id"]}))
    project = service.update_project(
        project.id,
        models.ProjectUpdateRequest(
            expected_revision=2,
            scenes=[scene.model_copy(update={"shots": linked})],
        ),
    )

    # QA94 diagnostic only: surface FFmpeg's synthetic-media stderr if the
    # actual application command fails. Production code still builds/runs the
    # unmodified command; no command flags or runtime behavior are changed.
    original_ffmpeg_runner = service._run_master_ffmpeg

    def _diagnostic_ffmpeg_runner(command, **kwargs):
        execution = original_ffmpeg_runner(command, **kwargs)
        if execution.returncode != 0:
            stderr = execution.stderr if isinstance(execution.stderr, str) else ""
            raise RuntimeError(
                f"Synthetic QA FFmpeg returned {execution.returncode}; "
                f"stderr tail: {stderr[-1800:]}"
            )
        return execution

    monkeypatch.setattr(service, "_run_master_ffmpeg", _diagnostic_ffmpeg_runner)

    result = service.assemble_project_master(
        project.id,
        requests.AssembleMasterRequest(expected_revision=project.revision),
    )
    assert result["status"] == "ready"
    assert result["actual_video_probe_verified"] is True
    assert result["source_shot_count"] == 60
    assert result["timeline_frames"] == 14_400
    assert result["timeline_seconds"] == pytest.approx(600.0)
    assert result["probe"]["codec"] == "h264"
    assert result["probe"]["fps"] == "24"
    assert result["probe"]["frame_count"] == 14_400
    assert result["probe"]["duration_seconds"] == pytest.approx(600.0, abs=0.05)

    output = storage.video_asset_path(result["asset_id"], "mp4")
    assert output.is_file() and output.stat().st_size > 1000
    with output.open("rb") as handle:
        assert hashlib.file_digest(handle, "sha256").hexdigest() == result["sha256"]

    # Decode every output frame; metadata alone cannot establish decodability.
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-v", "error", "-xerror",
            "-i", str(output), "-an", "-f", "null", "-",
        ],
        check=True, capture_output=True, text=True, timeout=600,
    )

    # Decode one center frame from every 10-second shot in a single pass.
    # This detects swapped, missing, duplicated or stale interior shots that
    # the earlier first/last-only acceptance cannot observe.
    samples = subprocess.run(
        [
            "ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(output),
            "-an", "-vf", r"select=eq(mod(n\,240)\,120),scale=1:1:flags=area",
            "-vsync", "0", "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
        ],
        check=True, capture_output=True, timeout=600,
    ).stdout
    assert len(samples) == 60 * 3, (
        f"Expected 60 shot centers; decoded {len(samples) // 3}"
    )
    for index, expected in enumerate(colors):
        actual = tuple(samples[index * 3 : index * 3 + 3])
        assert all(abs(a - e) <= 28 for a, e in zip(actual, expected)), (
            f"Shot {index + 1} center RGB {actual} differs from {expected}"
        )

    # A second request must reuse the verified SHA-linked artifact.
    again = service.assemble_project_master(
        project.id,
        requests.AssembleMasterRequest(expected_revision=project.revision),
    )
    assert again["asset_id"] == result["asset_id"]
    assert again["sha256"] == result["sha256"]
