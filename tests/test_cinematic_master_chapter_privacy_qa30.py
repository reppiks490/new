"""QA30: prevent FFmpeg source chapter titles leaking into private master MP4s.

Real synthetic H.264 media only. No owner assets, inference, or phone claims.
Strict test is opt-in because the production regression is expected RED until
the assembly owner explicitly suppresses chapter inheritance.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("CINEMATIC_REQUIRE_CHAPTER_PRIVACY_QA") != "1",
    reason="Opt-in real FFmpeg chapter-privacy acceptance; expected RED in production",
)


def _tools() -> tuple[str, str]:
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.fail("Strict QA30 requires local FFmpeg and FFprobe")
    return ffmpeg, ffprobe


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv, check=True, capture_output=True, text=True, timeout=120,
    )


def _chapters(ffprobe: str, video: Path) -> list[dict]:
    return json.loads(_run([
        ffprobe, "-v", "error", "-show_chapters", "-of", "json", str(video),
    ]).stdout)["chapters"]


def _chapter_source(tmp_path: Path, ffmpeg: str, ffprobe: str) -> Path:
    raw = tmp_path / "raw.mp4"
    source = tmp_path / "chapter_source.mp4"
    metadata = tmp_path / "synthetic_chapters.txt"
    _run([
        ffmpeg, "-nostdin", "-y", "-v", "error",
        "-f", "lavfi", "-i", "color=c=red:s=160x90:r=24:d=10",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(raw),
    ])
    metadata.write_text(
        ";FFMETADATA1\n[CHAPTER]\nTIMEBASE=1/1000\n"
        "START=0\nEND=1000\ntitle=SYNTHETIC_CHAPTER_SENTINEL\n",
        encoding="utf-8",
    )
    _run([
        ffmpeg, "-nostdin", "-y", "-v", "error",
        "-i", str(raw), "-f", "ffmetadata", "-i", str(metadata),
        "-map", "0:v:0", "-map_chapters", "1", "-map_metadata", "-1",
        "-c:v", "copy", str(source),
    ])
    assert len(_chapters(ffprobe, source)) == 1, "Synthetic chapter fixture missing"
    return source


def test_explicit_ffmpeg_chapter_suppression_preserves_decodable_video(tmp_path):
    """Independent real-media mitigation control, not production integration."""
    ffmpeg, ffprobe = _tools()
    source = _chapter_source(tmp_path, ffmpeg, ffprobe)
    clean = tmp_path / "explicitly_clean.mp4"
    _run([
        ffmpeg, "-nostdin", "-y", "-v", "error", "-i", str(source),
        "-filter_complex", "[0:v:0]fps=24,format=yuv420p[v]",
        "-map", "[v]", "-map_chapters", "-1", "-an",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(clean),
    ])
    assert _chapters(ffprobe, clean) == [], "Explicit chapter stripping failed"
    _run([ffmpeg, "-nostdin", "-v", "error", "-xerror",
          "-i", str(clean), "-f", "null", "-"])


def test_application_master_must_not_inherit_source_chapters(monkeypatch, tmp_path):
    """Expected RED: current real master assembler inherits source chapters."""
    ffmpeg, ffprobe = _tools()
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    from app.video import cinematic_models as models
    from app.video import cinematic_service as service
    from app.video.cinematic_requests import AssembleMasterRequest
    from app.video.storage import put_video_record, video_asset_path

    project = service.create_project(models.ProjectCreateRequest(
        title="Synthetic chapter privacy QA",
        master_prompt="Synthetic media, no inference or owner content.",
        target_duration_seconds=10, delivery_fps=24,
        delivery_resolution="480p", aspect_ratio="16:9",
    ))
    shot = models.CinematicShot(
        shot_id="a" * 32, ordinal=1, title="Synthetic shot",
        prompt="Synthetic footage only.", duration_seconds=10,
    )
    scene = models.CinematicScene(
        scene_id="b" * 32, ordinal=1, title="Synthetic scene",
        target_duration_seconds=10, shots=[shot],
    )
    project = service.update_project(
        project.id, models.ProjectUpdateRequest(
            expected_revision=1, scenes=[scene],
        ),
    )
    source = _chapter_source(tmp_path, ffmpeg, ffprobe)
    asset_id = "c" * 32
    shutil.copyfile(source, video_asset_path(asset_id, "mp4"))
    job = put_video_record("video_job", {
        "status": "succeeded", "project_id": project.id,
        "scene_id": scene.scene_id, "shot_id": shot.shot_id,
        "asset_id": asset_id, "project_revision": project.revision,
    })
    linked_shot = shot.model_copy(update={
        "latest_job_id": job["id"],
        "latest_rendered_project_revision": project.revision,
    })
    project = service.update_project(
        project.id, models.ProjectUpdateRequest(
            expected_revision=project.revision,
            scenes=[scene.model_copy(update={"shots": [linked_shot]})],
        ),
    )
    assert service.project_render_status(project.id)["ready_for_assembly"]
    master = service.assemble_project_master(
        project.id, AssembleMasterRequest(expected_revision=project.revision),
    )
    output = video_asset_path(master["asset_id"], "mp4")
    assert master["status"] == "ready"
    assert master["probe"]["probe_metadata_verified"] is True
    # Report only a chapter count, never the chapter title or private values.
    assert len(_chapters(ffprobe, output)) == 0, (
        "Assembled master retained source chapters; chapter metadata privacy violated"
    )
