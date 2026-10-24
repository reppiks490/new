"""QA32: genuine synthetic HDR-tagged source colorimetry through cinematic assembly.

Opt-in, expected-RED production contract until the assembly owner chooses an
explicit SDR delivery policy or a separately verified HDR delivery profile.
No owner media, model inference, GPU, or physical phone verification.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("CINEMATIC_REQUIRE_COLORIMETRY_QA") != "1",
    reason="Opt-in real-media SDR acceptance; production regression expected RED",
)


def _tools() -> tuple[str, str]:
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.fail("Strict QA32 requires FFmpeg and FFprobe")
    return ffmpeg, ffprobe


def _run(command: list[str], *, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, check=True, capture_output=True, text=True, timeout=timeout,
    )


def _video_stream(ffprobe: str, path: Path) -> dict:
    result = _run([
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries",
        "stream=codec_name,pix_fmt,color_space,color_transfer,color_primaries,nb_frames",
        "-of", "json", str(path),
    ])
    return json.loads(result.stdout)["streams"][0]


def _hdr_tagged_source(tmp_path: Path, ffmpeg: str, ffprobe: str) -> Path:
    """The pixels are synthetic; the H.264 BT.2020/PQ signal is genuine."""
    path = tmp_path / "synthetic_bt2020_pq.mp4"
    _run([
        ffmpeg, "-nostdin", "-y", "-v", "error",
        "-f", "lavfi", "-i", "color=c=red:s=160x90:r=24:d=10",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-x264-params", "colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc",
        str(path),
    ])
    stream = _video_stream(ffprobe, path)
    assert stream["color_transfer"] == "smpte2084"
    assert stream["color_primaries"] == "bt2020"
    assert stream["color_space"] == "bt2020nc"
    return path


def test_ffmpeg_reencode_can_preserve_pq_tags_without_tone_mapping(tmp_path):
    """Passing real-media reproduction, NOT proof of HDR pixel correctness."""
    ffmpeg, ffprobe = _tools()
    source = _hdr_tagged_source(tmp_path, ffmpeg, ffprobe)
    output = tmp_path / "synthetic_reencoded.mp4"
    _run([
        ffmpeg, "-nostdin", "-y", "-v", "error", "-i", str(source),
        "-filter_complex", "[0:v:0]fps=24,format=yuv420p[v]",
        "-map", "[v]", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(output),
    ])
    stream = _video_stream(ffprobe, output)
    assert stream["pix_fmt"] == "yuv420p"
    assert stream["color_transfer"] == "smpte2084"
    assert stream["color_primaries"] == "bt2020"
    _run([ffmpeg, "-nostdin", "-v", "error", "-xerror",
          "-i", str(output), "-f", "null", "-"])


def test_application_mobile_sdr_master_must_not_silently_retain_pq(
    monkeypatch, tmp_path,
):
    """Expected RED: 8-bit mobile H.264 master inherits source PQ color tags.

    Contract is conditional: an explicitly approved, separately verified HDR
    delivery mode could be valid. The current generic 8-bit mobile master has
    no such mode or tone-map policy.
    """
    ffmpeg, ffprobe = _tools()
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    from app.video import cinematic_models as models
    from app.video import cinematic_service as service
    from app.video.cinematic_requests import AssembleMasterRequest
    from app.video.storage import put_video_record, video_asset_path

    project = service.create_project(models.ProjectCreateRequest(
        title="Synthetic colorimetry QA",
        master_prompt="Synthetic footage only, no model inference.",
        target_duration_seconds=10, delivery_fps=24,
        delivery_resolution="480p", aspect_ratio="16:9",
    ))
    shot = models.CinematicShot(
        shot_id="a" * 32, ordinal=1, title="Synthetic shot",
        prompt="Synthetic colorimetry test.", duration_seconds=10,
    )
    scene = models.CinematicScene(
        scene_id="b" * 32, ordinal=1, title="Synthetic scene",
        target_duration_seconds=10, shots=[shot],
    )
    project = service.update_project(
        project.id, models.ProjectUpdateRequest(expected_revision=1, scenes=[scene]),
    )
    source = _hdr_tagged_source(tmp_path, ffmpeg, ffprobe)
    asset_id = "c" * 32
    shutil.copyfile(source, video_asset_path(asset_id, "mp4"))
    job = put_video_record("video_job", {
        "status": "succeeded", "project_id": project.id,
        "scene_id": scene.scene_id, "shot_id": shot.shot_id,
        "asset_id": asset_id, "project_revision": project.revision,
    })
    linked = shot.model_copy(update={
        "latest_job_id": job["id"],
        "latest_rendered_project_revision": project.revision,
    })
    project = service.update_project(
        project.id, models.ProjectUpdateRequest(
            expected_revision=project.revision,
            scenes=[scene.model_copy(update={"shots": [linked]})],
        ),
    )
    assert service.project_render_status(project.id)["ready_for_assembly"]
    master = service.assemble_project_master(
        project.id, AssembleMasterRequest(expected_revision=project.revision),
    )
    assert master["status"] == "ready"
    assert master["probe"]["probe_metadata_verified"] is True
    output = video_asset_path(master["asset_id"], "mp4")
    stream = _video_stream(ffprobe, output)
    assert stream["codec_name"] == "h264"
    assert stream["pix_fmt"] == "yuv420p"
    # SDR mobile acceptance must not silently publish a PQ-tagged 8-bit
    # master. Do not merely relabel PQ pixels as SDR: convert/tonemap or
    # reject unsupported source colorimetry before publication.
    assert stream.get("color_transfer") != "smpte2084", (
        "Generic 8-bit mobile master retained source PQ transfer metadata"
    )
