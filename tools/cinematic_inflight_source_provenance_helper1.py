"""Deterministic genuine-FFmpeg test for in-flight cinematic source provenance.

Only the scheduling seam is instrumented: a synthetic source is replaced
AFTER the service fingerprints it but BEFORE the real FFmpeg subprocess
opens it. Both source generations and the master use actual libx264, ffprobe
and full decoding. This is an isolated QA contract, not an exploit script,
owner-footage test, or proposed change to lead-owned production files.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
from uuid import uuid4

from app.video import cinematic_models as models
from app.video import cinematic_service as service
from app.video import storage
from app.video.cinematic_requests import AssembleMasterRequest


def real_command(*args: str) -> bytes:
    return subprocess.run(args, check=True, capture_output=True, timeout=120).stdout


def encode_synthetic(path: Path, color: str) -> None:
    real_command(
        "ffmpeg", "-nostdin", "-y", "-v", "error",
        "-f", "lavfi", "-i", f"color=c={color}:s=160x90:r=24:d=10",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(path),
    )


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class InFlightSourceProvenance(unittest.TestCase):
    def make_ready_project(self):
        created = service.create_project(models.ProjectCreateRequest(
            title="Synthetic in-flight provenance QA",
            master_prompt="SYNTHETIC_PRIVATE_INFLIGHT_CANARY",
            target_duration_seconds=10, delivery_fps=24,
            delivery_resolution="480p", aspect_ratio="16:9",
            reference_image_ids=[],
        ))
        scene_id, shot_id, asset_id = uuid4().hex, uuid4().hex, uuid4().hex
        shot = models.CinematicShot(
            shot_id=shot_id, ordinal=1, title="Synthetic source",
            prompt="Solid synthetic color", duration_seconds=10,
        )
        scene = models.CinematicScene(
            scene_id=scene_id, ordinal=1, title="Synthetic scene",
            target_duration_seconds=10, shots=[shot],
        )
        project = service.update_project(
            created.id,
            models.ProjectUpdateRequest(expected_revision=1, scenes=[scene]),
        )
        source = storage.video_asset_path(asset_id, "mp4")
        encode_synthetic(source, "red")
        render = storage.put_video_record("video_job", {
            "status": "succeeded", "stage": "Ready", "progress": 100,
            "project_id": project.id, "scene_id": scene_id,
            "shot_id": shot_id, "project_revision": 2,
            "asset_id": asset_id,
            "asset_url": f"/api/video/assets/{asset_id}.mp4",
        })
        project = service.update_project(
            project.id, models.ProjectUpdateRequest(
                expected_revision=2,
                scenes=[scene.model_copy(update={"shots": [
                    shot.model_copy(update={
                        "latest_job_id": render["id"],
                        "latest_rendered_project_revision": 2,
                    }),
                ]})],
            ),
        )
        self.assertEqual(project.revision, 3)
        self.assertTrue(service.project_render_status(project.id)["ready_for_assembly"])
        return project, source

    def assert_real_media(self, record: dict, expected_color: str):
        output = storage.video_asset_path(record["asset_id"], "mp4")
        self.assertEqual(sha256(output), record["sha256"])
        info = json.loads(real_command(
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,width,height,nb_frames",
            "-of", "json", str(output),
        ))
        video = info["streams"][0]
        self.assertEqual(video["codec_name"], "h264")
        self.assertEqual((video["width"], video["height"]), (854, 480))
        self.assertEqual(int(video["nb_frames"]), 240)
        real_command(
            "ffmpeg", "-nostdin", "-v", "error", "-xerror",
            "-i", str(output), "-an", "-f", "null", "-",
        )
        pixel = real_command(
            "ffmpeg", "-nostdin", "-v", "error", "-ss", "5",
            "-i", str(output), "-vf", "scale=1:1", "-frames:v", "1",
            "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
        )
        self.assertEqual(len(pixel), 3)
        index = {"red": 0, "green": 1, "blue": 2}[expected_color]
        self.assertGreater(pixel[index], max(
            value for i, value in enumerate(pixel) if i != index
        ) + 65)

    def test_unchanged_source_is_correctly_hashed_and_cached(self):
        project, source = self.make_ready_project()
        request = AssembleMasterRequest(expected_revision=project.revision)
        first = service.assemble_project_master(project.id, request)
        self.assertEqual(first["source_asset_hashes"], [sha256(source)])
        self.assertTrue(first["actual_video_probe_verified"])
        self.assert_real_media(first, "red")
        second = service.assemble_project_master(project.id, request)
        self.assertEqual(second["id"], first["id"])

    def test_source_replaced_between_fingerprint_and_real_ffmpeg_must_not_publish_stale_lineage(self):
        project, source = self.make_ready_project()
        request = AssembleMasterRequest(expected_revision=project.revision)
        preflight_sha = sha256(source)
        original_runner = service._run_master_ffmpeg
        mutations = []

        def replace_then_run_actual_ffmpeg(command, **kwargs):
            # Deterministic scheduling seam only; real FFmpeg still encodes,
            # assembles, probes, and fully decodes every synthetic MP4.
            encode_synthetic(source, "blue")
            mutations.append(sha256(source))
            return original_runner(command, **kwargs)

        with patch.object(service, "_run_master_ffmpeg",
                          side_effect=replace_then_run_actual_ffmpeg):
            try:
                master = service.assemble_project_master(project.id, request)
            except service.MasterAssemblyNotReady:
                # An explicit fail-closed rejection is also acceptable.
                self.assertEqual(len(mutations), 1)
                self.assertNotEqual(mutations[0], preflight_sha)
                self.assertFalse([
                    row for row in storage.list_video_records("video_master")
                    if row.get("project_id") == project.id
                    and row.get("status") == "ready"
                ])
                return

        self.assertEqual(len(mutations), 1, "Mutation hook must execute once")
        self.assertNotEqual(mutations[0], preflight_sha)
        self.assert_real_media(master, "blue")
        # RED on the current service: fingerprint/source hashes are captured
        # before FFmpeg opens the mutated source. A ready master must never
        # attest the OLD red bytes while containing NEW blue decoded frames.
        self.assertEqual(
            master["source_asset_hashes"], [sha256(source)],
            "Published source SHA-256 lineage must match bytes actually assembled",
        )
        self.assertEqual(
            service.assemble_project_master(project.id, request)["id"],
            master["id"],
            "Corrected source fingerprint must remain a stable cache identity",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
