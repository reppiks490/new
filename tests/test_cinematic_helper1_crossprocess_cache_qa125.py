"""QA125: genuine cross-process master cache identity, invalidation and integrity.

Only synthetic FFmpeg color clips and disposable SQLite workspace are used.
The same project is assembled from four separate Python interpreters. No
private media, model inference, paid service, or production mutation.
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

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("CINEMATIC_HELPER1_CACHE_QA125") != "1",
    reason="opt-in genuine FFmpeg cross-process cache integrity acceptance",
)

_CHILD = r"""
import json
import sys
from app.video.cinematic_requests import AssembleMasterRequest
from app.video.cinematic_service import assemble_project_master

project_id, revision = sys.argv[1], int(sys.argv[2])
master = assemble_project_master(
    project_id, AssembleMasterRequest(expected_revision=revision)
)
print(json.dumps({
    "id": master["id"],
    "asset_id": master["asset_id"],
    "sha256": master["sha256"],
    "source_digest": master["source_digest"],
    "probe_verified": master["probe"]["probe_metadata_verified"],
    "project_id": master["project_id"],
    "project_revision": master["project_revision"],
}), flush=True)
"""


def _run(command, *, cwd=None, env=None, timeout=180):
    return subprocess.run(
        command, cwd=cwd, env=env, check=True, capture_output=True,
        text=True, timeout=timeout,
    )


def _encode(ffmpeg: str, destination: Path, color: str, fps: int) -> None:
    _run([
        ffmpeg, "-nostdin", "-y", "-v", "error", "-f", "lavfi",
        "-i", f"color=c={color}:s=160x90:r={fps}:d=5",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(destination),
    ])
    assert destination.is_file() and destination.stat().st_size > 128


def _make_project(monkeypatch, workspace: Path, ffmpeg: str):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(workspace))
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    storage = importlib.import_module("app.video.storage")

    project = service.create_project(models.ProjectCreateRequest(
        title="QA125 synthetic cross-process cache",
        master_prompt="QA125_PRIVATE_CREATIVE_TEXT",
        target_duration_seconds=10,
        delivery_fps=24,
        delivery_resolution="480p",
        aspect_ratio="16:9",
    ))
    shots = [
        models.CinematicShot(
            shot_id=f"{index + 400:032x}", ordinal=index + 1,
            title=f"Synthetic clip {index + 1}",
            prompt="Local disposable FFmpeg color", duration_seconds=5,
        )
        for index in range(2)
    ]
    scene = models.CinematicScene(
        scene_id="a" * 32, ordinal=1, title="Offline synthetic test",
        target_duration_seconds=10, shots=shots,
    )
    project = service.update_project(
        project.id,
        models.ProjectUpdateRequest(expected_revision=1, scenes=[scene]),
    )
    linked = []
    source_paths = []
    for index, (color, fps) in enumerate((("red", 24), ("blue", 30))):
        asset_id = f"{index + 450:032x}"
        path = storage.video_asset_path(asset_id, "mp4")
        _encode(ffmpeg, path, color, fps)
        source_paths.append(path)
        record = storage.put_video_record("video_job", {
            "status": "succeeded",
            "project_id": project.id,
            "scene_id": scene.scene_id,
            "shot_id": shots[index].shot_id,
            "project_revision": project.revision,
            "asset_id": asset_id,
            "asset_url": f"/api/video/assets/{asset_id}.mp4",
        })
        linked.append(shots[index].model_copy(update={
            "latest_job_id": record["id"],
            "latest_rendered_project_revision": project.revision,
        }))
    project = service.update_project(
        project.id,
        models.ProjectUpdateRequest(
            expected_revision=2,
            scenes=[scene.model_copy(update={"shots": linked})],
        ),
    )
    assert project.revision == 3
    assert service.project_render_status(project.id)["ready_for_assembly"]
    return project, storage, source_paths


def test_cache_reuse_source_mutation_and_tamper_across_fresh_interpreters(
    monkeypatch, tmp_path: Path,
):
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    assert ffmpeg and ffprobe, "Dedicated QA125 requires real FFmpeg and FFprobe"
    project, storage, sources = _make_project(monkeypatch, tmp_path, ffmpeg)
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(root), env.get("PYTHONPATH", "")) if part
    )

    def assemble_in_fresh_process():
        process = _run(
            [sys.executable, "-u", "-c", _CHILD, project.id,
             str(project.revision)],
            cwd=root, env=env,
        )
        assert "QA125_PRIVATE_CREATIVE_TEXT" not in process.stdout + process.stderr
        result = json.loads(process.stdout.strip())
        assert result["project_id"] == project.id
        assert result["project_revision"] == project.revision
        assert result["probe_verified"] is True
        path = storage.video_asset_path(result["asset_id"], "mp4")
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == result["sha256"]
        return result, path

    first, first_path = assemble_in_fresh_process()
    # A second process must find the probe-verified, hash-verified cache.
    second, second_path = assemble_in_fresh_process()
    assert (second["id"], second["asset_id"], second["sha256"]) == (
        first["id"], first["asset_id"], first["sha256"]
    )
    assert second_path == first_path

    # Source MP4 bytes change without changing its opaque asset ID or project
    # revision. A previously cached master must NOT be silently reused.
    before = hashlib.sha256(sources[1].read_bytes()).hexdigest()
    _encode(ffmpeg, sources[1], "green", 30)
    assert hashlib.sha256(sources[1].read_bytes()).hexdigest() != before
    changed, changed_path = assemble_in_fresh_process()
    assert changed["id"] != first["id"]
    assert changed["source_digest"] != first["source_digest"]
    assert changed["sha256"] != first["sha256"]

    # Tamper with the cached master while leaving its database metadata
    # unchanged. The next process must reject that cache and re-encode.
    with changed_path.open("ab") as stream:
        stream.write(b"QA125_TAMPER_BYTES")
    assert hashlib.sha256(changed_path.read_bytes()).hexdigest() != changed["sha256"]
    repaired, repaired_path = assemble_in_fresh_process()
    assert repaired["id"] != changed["id"]
    assert repaired["source_digest"] == changed["source_digest"]
    assert repaired["sha256"] == changed["sha256"]

    # Actual FFprobe and full decode on all *published* distinct masters.
    for record, path in ((first, first_path), (repaired, repaired_path)):
        metadata = json.loads(_run([
            ffprobe, "-v", "error", "-show_streams", "-show_format",
            "-of", "json", str(path),
        ]).stdout)
        videos = [s for s in metadata["streams"] if s["codec_type"] == "video"]
        assert len(videos) == 1
        assert videos[0]["codec_name"] == "h264"
        assert (videos[0]["width"], videos[0]["height"]) == (854, 480)
        assert int(videos[0]["nb_frames"]) == 240
        assert float(metadata["format"]["duration"]) == pytest.approx(10, abs=0.25)
        _run([
            ffmpeg, "-nostdin", "-v", "error", "-xerror",
            "-i", str(path), "-an", "-f", "null", "-",
        ])
