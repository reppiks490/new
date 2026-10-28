"""QA126: source-file TOCTOU attestation during real synthetic master assembly.

A disposable local FFmpeg clip is atomically replaced after the service hashes
its inputs but immediately before the real FFmpeg process opens them. This
reproduces a stale source-hash provenance record, not a remote exploit.
No owner media, model inference, paid services, or multi-server assumptions.
"""
from __future__ import annotations

import hashlib
import importlib
import os
from pathlib import Path
import shutil
import subprocess

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("CINEMATIC_SOURCE_MUTATION_QA126") != "1",
    reason="opt-in genuine synthetic FFmpeg source-mutation acceptance",
)


class SourceMediaChangedDuringAssembly(AssertionError):
    """A published master attests a source hash different from its consumed bytes."""


def _run(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=True, capture_output=True, timeout=180)


def _encode(ffmpeg: str, destination: Path, color: str, fps: int) -> None:
    _run([
        ffmpeg, "-nostdin", "-y", "-v", "error", "-f", "lavfi",
        "-i", f"color=c={color}:s=160x90:r={fps}:d=5",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(destination),
    ])
    assert destination.is_file() and destination.stat().st_size > 128


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _project(monkeypatch, workspace: Path, ffmpeg: str):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(workspace))
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    storage = importlib.import_module("app.video.storage")
    project = service.create_project(models.ProjectCreateRequest(
        title="QA126 disposable source mutation",
        master_prompt="QA126_PRIVATE_CREATIVE_SENTINEL",
        target_duration_seconds=10,
        delivery_fps=24,
        delivery_resolution="480p",
        aspect_ratio="16:9",
    ))
    shots = [
        models.CinematicShot(
            shot_id=f"{index + 560:032x}", ordinal=index + 1,
            title=f"Disposable color {index + 1}",
            prompt="Offline synthetic FFmpeg color",
            duration_seconds=5,
        )
        for index in range(2)
    ]
    scene = models.CinematicScene(
        scene_id="b" * 32, ordinal=1, title="Disposable source race",
        target_duration_seconds=10, shots=shots,
    )
    project = service.update_project(
        project.id, models.ProjectUpdateRequest(expected_revision=1, scenes=[scene])
    )
    linked = []
    sources = []
    for index, (color, fps) in enumerate((("red", 24), ("blue", 30))):
        asset_id = f"{index + 580:032x}"
        path = storage.video_asset_path(asset_id, "mp4")
        _encode(ffmpeg, path, color, fps)
        sources.append(path)
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
        project.id, models.ProjectUpdateRequest(
            expected_revision=2,
            scenes=[scene.model_copy(update={"shots": linked})],
        ),
    )
    assert project.revision == 3
    assert service.project_render_status(project.id)["ready_for_assembly"]
    return project, sources, service, models


def test_stable_sources_have_truthful_published_hashes(monkeypatch, tmp_path: Path):
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg and shutil.which("ffprobe"), "QA126 requires real FFmpeg/FFprobe"
    project, sources, service, _ = _project(monkeypatch, tmp_path, ffmpeg)
    from app.video.cinematic_requests import AssembleMasterRequest
    master = service.assemble_project_master(
        project.id, AssembleMasterRequest(expected_revision=project.revision)
    )
    assert master["status"] == "ready"
    assert master["actual_video_probe_verified"] is True
    assert master["source_asset_hashes"] == [_sha(path) for path in sources]


@pytest.mark.xfail(
    raises=SourceMediaChangedDuringAssembly,
    strict=True,
    reason="QA126 confirmed: master attests pre-FFmpeg source hash after source replacement",
)
def test_source_replacement_during_ffmpeg_must_not_publish_stale_attestation(
    monkeypatch, tmp_path: Path,
):
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg and shutil.which("ffprobe"), "QA126 requires real FFmpeg/FFprobe"
    project, sources, service, _ = _project(monkeypatch, tmp_path, ffmpeg)
    from app.video.cinematic_requests import AssembleMasterRequest
    initial = _sha(sources[1])
    original = service._run_master_ffmpeg
    injected = []

    def replace_source_before_actual_ffmpeg(command, **kwargs):
        # The production function already hashed both sources at this point.
        assert not injected, "Only one real FFmpeg invocation should occur"
        replacement = tmp_path / "qa126-replacement.mp4"
        _encode(ffmpeg, replacement, "green", 30)
        os.replace(replacement, sources[1])
        injected.append(_sha(sources[1]))
        assert injected[0] != initial
        return original(command, **kwargs)

    monkeypatch.setattr(service, "_run_master_ffmpeg", replace_source_before_actual_ffmpeg)
    master = service.assemble_project_master(
        project.id, AssembleMasterRequest(expected_revision=project.revision)
    )
    assert injected, "Mutation hook was not exercised"
    assert master["status"] == "ready"
    assert master["actual_video_probe_verified"] is True
    assert master["source_asset_hashes"][1] == initial

    # Confirm the *actual* rendered output consumed the new green source.
    from app.video.storage import video_asset_path
    output = video_asset_path(master["asset_id"], "mp4")
    pixel = _run([
        ffmpeg, "-nostdin", "-v", "error", "-ss", "7",
        "-i", str(output), "-frames:v", "1", "-vf", "scale=1:1",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
    ]).stdout
    assert len(pixel) == 3
    assert pixel[1] > 90 and pixel[1] > pixel[0] + 60 and pixel[1] > pixel[2] + 60
    actual_source_hash = _sha(sources[1])
    assert actual_source_hash == injected[0]
    if master["source_asset_hashes"][1] != actual_source_hash:
        raise SourceMediaChangedDuringAssembly(
            "Published master consumed replacement green clip but attested "
            "the original blue clip SHA-256; source changed after pre-encode hashing"
        )
