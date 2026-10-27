"""QA100: opt-in synthetic AAC source-audio preservation acceptance.

Genuine local FFmpeg source MP4s and application master assembly. This is
not model inference, owner media, owner-PC playback or physical phone QA.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("CINEMATIC_SOURCE_AUDIO_QA") != "1",
    reason="Genuine synthetic AAC source-audio acceptance is opt-in",
)


def _run(command: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=True, capture_output=True, timeout=timeout)


def _streams(path: Path) -> list[dict]:
    raw = _run([
        "ffprobe", "-v", "error", "-show_entries",
        "stream=codec_type,codec_name,sample_rate,channels:format=duration",
        "-of", "json", str(path),
    ])
    return json.loads(raw.stdout)["streams"]


def _tone_at(path: Path, seconds: float) -> float:
    """Independent decoded PCM zero-crossing frequency estimate (no numpy)."""
    duration = 0.25
    pcm = _run([
        "ffmpeg", "-nostdin", "-v", "error", "-xerror",
        "-ss", str(seconds), "-i", str(path),
        "-map", "0:a:0", "-t", str(duration),
        "-ac", "1", "-ar", "48000", "-f", "s16le", "-",
    ], timeout=90).stdout
    import array
    samples = array.array("h")
    samples.frombytes(pcm)
    assert len(samples) >= 10_000, "Insufficient decoded audio samples"
    assert max(samples) - min(samples) > 100, "Master audio is silent"
    crossings = sum(a <= 0 < b for a, b in zip(samples, samples[1:]))
    return crossings / (len(samples) / 48000)


class SourceAudioDiscarded(AssertionError):
    """Only the confirmed absent-source-audio failure is expected."""


@pytest.mark.xfail(
    strict=True,
    raises=SourceAudioDiscarded,
    reason="Unimplemented: master assembly explicitly discards source AAC (-an)",
)
def test_assembled_master_preserves_distinct_source_aac_tones(monkeypatch, tmp_path: Path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.fail("Dedicated source-audio QA requires local FFmpeg and FFprobe")
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    storage = importlib.import_module("app.video.storage")
    requests = importlib.import_module("app.video.cinematic_requests")

    source_ids = []
    for index, (color, frequency) in enumerate((("red", 440), ("blue", 880))):
        asset_id = f"{index + 500:032x}"
        path = storage.video_asset_path(asset_id, "mp4")
        _run([
            "ffmpeg", "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=160x90:r=24:d=5",
            "-f", "lavfi", "-i",
            f"sine=frequency={frequency}:sample_rate=48000:duration=5",
            "-c:v", "mpeg4", "-q:v", "4", "-c:a", "aac", "-b:a", "96k",
            "-shortest", str(path),
        ])
        streams = _streams(path)
        assert any(s["codec_type"] == "video" for s in streams)
        assert any(s["codec_type"] == "audio" and s["codec_name"] == "aac"
                   for s in streams)
        assert abs(_tone_at(path, 2.5) - frequency) < 10
        source_ids.append(asset_id)

    project = service.create_project(models.ProjectCreateRequest(
        title="QA100 offline synthetic AAC source preservation",
        master_prompt="Local generated color and sine tones only.",
        target_duration_seconds=10, delivery_fps=24,
        delivery_resolution="480p", aspect_ratio="16:9",
    ))
    shots = [
        models.CinematicShot(
            shot_id=f"{index + 600:032x}", ordinal=index + 1,
            title=f"Tone {index + 1}", prompt="Synthetic color and audio only.",
            duration_seconds=5,
        )
        for index in range(2)
    ]
    scene = models.CinematicScene(
        scene_id="7" * 32, ordinal=1, title="Audio source control",
        target_duration_seconds=10, shots=shots,
    )
    project = service.update_project(project.id, models.ProjectUpdateRequest(
        expected_revision=1, scenes=[scene],
    ))
    linked = []
    for shot, asset_id in zip(shots, source_ids):
        record = storage.put_video_record("video_job", {
            "status": "succeeded", "project_id": project.id,
            "scene_id": scene.scene_id, "shot_id": shot.shot_id,
            "project_revision": project.revision,
            "asset_id": asset_id,
            "asset_url": f"/api/video/assets/{asset_id}.mp4",
        })
        linked.append(shot.model_copy(update={"latest_job_id": record["id"]}))
    project = service.update_project(project.id, models.ProjectUpdateRequest(
        expected_revision=2,
        scenes=[scene.model_copy(update={"shots": linked})],
    ))

    result = service.assemble_project_master(
        project.id, requests.AssembleMasterRequest(expected_revision=project.revision),
    )
    master = storage.video_asset_path(result["asset_id"], "mp4")
    assert result["status"] == "ready"
    assert result["probe"]["frame_count"] == 240
    assert result["probe"]["duration_seconds"] == pytest.approx(10, abs=0.05)
    with master.open("rb") as handle:
        assert hashlib.file_digest(handle, "sha256").hexdigest() == result["sha256"]
    _run(["ffmpeg", "-nostdin", "-v", "error", "-xerror",
          "-i", str(master), "-f", "null", "-"], timeout=180)

    output_streams = _streams(master)
    assert any(s["codec_type"] == "video" for s in output_streams)
    audio = [s for s in output_streams if s["codec_type"] == "audio"]
    if not audio:
        assert result.get("has_audio") is False, (
            "Audio-free master must not falsely advertise an audio track"
        )
        raise SourceAudioDiscarded(
            "Genuine source AAC streams were discarded by master assembly"
        )
    assert result.get("has_audio") is True, "Master metadata does not attest audio"
    assert abs(_tone_at(master, 2.5) - 440) < 10
    assert abs(_tone_at(master, 7.5) - 880) < 10
