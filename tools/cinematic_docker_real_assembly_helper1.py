"""Actual cinematic Docker integration: HTTP queue -> FFmpeg master -> private download.

Runs only inside the opt-in, offline, ephemeral cinematic container. Every input
is a locally generated color clip; never loads owner footage or credentials.
The older Docker smoke gate merely verified that FFmpeg was installed and could
encode an unrelated clip. This verifies the *cinematic service* uses it.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

from app.video import cinematic_models as models
from app.video import cinematic_service as service
from app.video import storage

BASE = "http://127.0.0.1:8000"


def run(*args: str, timeout: int = 120) -> bytes:
    return subprocess.run(
        list(args), check=True, capture_output=True, timeout=timeout
    ).stdout


def api(method: str, path: str, payload: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    request = Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=20) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read()
    except HTTPError as error:
        return error.code, {k.lower(): v for k, v in error.headers.items()}, error.read()


def json_api(method: str, path: str, payload: dict | None = None):
    code, headers, body = api(method, path, payload)
    return code, headers, json.loads(body)


def synthetic_clip(path: Path, color: str, fps: int) -> None:
    run("ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi",
        "-i", f"color=c={color}:s=160x90:r={fps}:d=5",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(path))
    assert path.is_file() and path.stat().st_size > 128


class RealCinematicDockerAssembly(unittest.TestCase):
    def test_actual_http_async_assembly_and_verified_private_master(self):
        # The CI container has --network none, no host mounts, no credentials,
        # and a tmpfs workspace. All records and media are disposable.
        created = service.create_project(models.ProjectCreateRequest(
            title="Offline Docker synthetic film",
            master_prompt="SYNTHETIC_PRIVATE_SCRIPT_CANARY red then blue",
            target_duration_seconds=10,
            delivery_fps=24,
            delivery_resolution="480p",
            aspect_ratio="16:9",
            reference_image_ids=[],
        ))
        scene_id = uuid4().hex
        shots = [
            models.CinematicShot(
                shot_id=uuid4().hex, ordinal=i + 1, title=f"Clip {i+1}",
                prompt="Synthetic color only", duration_seconds=5,
            ) for i in range(2)
        ]
        scene = models.CinematicScene(
            scene_id=scene_id, ordinal=1, title="Color slate",
            target_duration_seconds=10, shots=shots,
        )
        project = service.update_project(
            created.id,
            models.ProjectUpdateRequest(expected_revision=1, scenes=[scene]),
        )
        self.assertEqual(project.revision, 2)

        linked = []
        sources = []
        for i, (color, fps) in enumerate((("red", 24), ("blue", 30))):
            asset_id = uuid4().hex
            path = storage.video_asset_path(asset_id, "mp4")
            synthetic_clip(path, color, fps)
            sources.append(path)
            record = storage.put_video_record("video_job", {
                "status": "succeeded", "stage": "Ready", "progress": 100,
                "project_id": project.id, "scene_id": scene_id,
                "shot_id": shots[i].shot_id, "project_revision": 2,
                "asset_id": asset_id,
                "asset_url": f"/api/video/assets/{asset_id}.mp4",
            })
            linked.append(shots[i].model_copy(update={
                "latest_job_id": record["id"],
                "latest_rendered_project_revision": 2,
            }))

        project = service.update_project(
            project.id, models.ProjectUpdateRequest(
                expected_revision=2,
                scenes=[scene.model_copy(update={"shots": linked})],
            ),
        )
        self.assertEqual(project.revision, 3)
        self.assertTrue(service.project_render_status(project.id)["ready_for_assembly"])

        endpoint = f"/api/video/projects/{project.id}/assembly-jobs"
        code, _, queued = json_api("POST", endpoint, {"expected_revision": 3})
        self.assertEqual(code, 202, queued)
        self.assertEqual(queued["status"], "queued")
        self.assertNotIn("SYNTHETIC_PRIVATE_SCRIPT_CANARY", json.dumps(queued))
        job_path = f"{endpoint}/{queued['id']}"
        deadline = time.monotonic() + 120
        while True:
            code, _, job = json_api("GET", job_path)
            self.assertEqual(code, 200, job)
            if job["status"] in {"succeeded", "failed", "cancelled"}:
                break
            self.assertLess(time.monotonic(), deadline, "Real FFmpeg queue timed out")
            time.sleep(0.35)
        self.assertEqual(job["status"], "succeeded", job)
        self.assertTrue(job["probe_metadata_verified"])
        self.assertNotIn("SYNTHETIC_PRIVATE_SCRIPT_CANARY", json.dumps(job))
        self.assertTrue(job["asset_url"].startswith("/api/video/assets/"))
        code, headers, media = api("GET", job["asset_url"])
        self.assertEqual(code, 200)
        self.assertEqual(headers.get("cache-control"), "no-store")
        self.assertTrue(headers.get("content-type", "").startswith("video/mp4"))
        self.assertEqual(hashlib.sha256(media).hexdigest(), job["sha256"])
        self.assertIn(b"ftyp", media[:12])

        master = storage.get_video_record("video_master", job["master_id"])
        output = storage.video_asset_path(job["asset_id"], "mp4")
        self.assertEqual(master["project_id"], project.id)
        self.assertEqual(master["project_revision"], 3)
        self.assertEqual(output.read_bytes(), media)
        self.assertEqual(master["source_asset_hashes"], [
            hashlib.sha256(path.read_bytes()).hexdigest() for path in sources
        ])
        probe = json.loads(run(
            "ffprobe", "-v", "error", "-show_format", "-show_streams",
            "-of", "json", str(output)
        ))
        videos = [s for s in probe["streams"] if s["codec_type"] == "video"]
        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]["codec_name"], "h264")
        self.assertEqual((videos[0]["width"], videos[0]["height"]), (854, 480))
        self.assertEqual(int(videos[0]["nb_frames"]), 240)
        self.assertAlmostEqual(float(probe["format"]["duration"]), 10.0, delta=0.25)
        run("ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i",
            str(output), "-an", "-f", "null", "-")
        for second, channel in ((1, 0), (7, 2)):
            pixel = run(
                "ffmpeg", "-nostdin", "-v", "error", "-ss", str(second),
                "-i", str(output), "-frames:v", "1", "-vf", "scale=1:1",
                "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
            )
            self.assertEqual(len(pixel), 3)
            self.assertGreater(pixel[channel], 100)
            self.assertGreater(pixel[channel], pixel[2 - channel] + 60)

        # A second real queue job must reuse the same verified master bytes.
        code, _, retry = json_api("POST", endpoint, {"expected_revision": 3})
        self.assertEqual(code, 202, retry)
        self.assertNotEqual(retry["id"], queued["id"])
        retry_path = f"{endpoint}/{retry['id']}"
        deadline = time.monotonic() + 120
        while True:
            code, _, second = json_api("GET", retry_path)
            self.assertEqual(code, 200)
            if second["status"] in {"succeeded", "failed", "cancelled"}:
                break
            self.assertLess(time.monotonic(), deadline, "Cache retry timed out")
            time.sleep(0.35)
        self.assertEqual(second["status"], "succeeded", second)
        self.assertEqual(second["master_id"], job["master_id"])
        self.assertEqual(second["sha256"], job["sha256"])
        self.assertEqual(len(storage.list_video_records("video_master")), 1)
        self.assertEqual(service.get_project(project.id).revision, 3)

        # Critical provenance regression: the asset ID and project revision
        # stay unchanged, but the underlying source MP4 bytes change. A
        # hash-verified cached master MUST NOT be returned for these new bytes.
        original_master_sha = job["sha256"]
        original_blue_sha = hashlib.sha256(sources[1].read_bytes()).hexdigest()
        synthetic_clip(sources[1], "green", 30)
        green_sha = hashlib.sha256(sources[1].read_bytes()).hexdigest()
        self.assertNotEqual(green_sha, original_blue_sha)
        self.assertEqual(service.get_project(project.id).revision, 3)

        code, _, changed_receipt = json_api(
            "POST", endpoint, {"expected_revision": 3}
        )
        self.assertEqual(code, 202, changed_receipt)
        self.assertNotEqual(changed_receipt["id"], retry["id"])
        changed_path = f"{endpoint}/{changed_receipt['id']}"
        deadline = time.monotonic() + 120
        while True:
            code, _, changed = json_api("GET", changed_path)
            self.assertEqual(code, 200, changed)
            if changed["status"] in {"succeeded", "failed", "cancelled"}:
                break
            self.assertLess(time.monotonic(), deadline, "Source mutation rebuild timed out")
            time.sleep(0.35)
        self.assertEqual(changed["status"], "succeeded", changed)
        self.assertNotEqual(changed["master_id"], job["master_id"])
        self.assertNotEqual(changed["sha256"], original_master_sha)
        self.assertEqual(len(storage.list_video_records("video_master")), 2)
        rebuilt = storage.get_video_record("video_master", changed["master_id"])
        self.assertEqual(rebuilt["project_id"], project.id)
        self.assertEqual(rebuilt["project_revision"], 3)
        self.assertEqual(rebuilt["source_asset_hashes"], [
            hashlib.sha256(path.read_bytes()).hexdigest() for path in sources
        ])
        self.assertEqual(rebuilt["source_asset_hashes"][1], green_sha)

        rebuilt_output = storage.video_asset_path(changed["asset_id"], "mp4")
        code, headers, rebuilt_media = api("GET", changed["asset_url"])
        self.assertEqual(code, 200)
        self.assertEqual(headers.get("cache-control"), "no-store")
        self.assertEqual(hashlib.sha256(rebuilt_media).hexdigest(), changed["sha256"])
        self.assertEqual(rebuilt_output.read_bytes(), rebuilt_media)
        new_probe = json.loads(run(
            "ffprobe", "-v", "error", "-show_streams", "-of", "json",
            str(rebuilt_output),
        ))
        new_videos = [s for s in new_probe["streams"] if s["codec_type"] == "video"]
        self.assertEqual(len(new_videos), 1)
        self.assertEqual(int(new_videos[0]["nb_frames"]), 240)
        run("ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i",
            str(rebuilt_output), "-an", "-f", "null", "-")
        green_pixel = run(
            "ffmpeg", "-nostdin", "-v", "error", "-ss", "7",
            "-i", str(rebuilt_output), "-frames:v", "1",
            "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt",
            "rgb24", "pipe:1",
        )
        self.assertEqual(len(green_pixel), 3)
        self.assertGreater(green_pixel[1], 80)
        self.assertGreater(green_pixel[1], green_pixel[0] + 60)
        self.assertGreater(green_pixel[1], green_pixel[2] + 60)

        # Retain old historical master bytes without ever confusing the cache
        # for the current source fingerprint.
        self.assertEqual(
            hashlib.sha256(output.read_bytes()).hexdigest(), original_master_sha
        )
        self.assertEqual(service.get_project(project.id).revision, 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
