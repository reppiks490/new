"""Real FFmpeg cinematic master over token-protected HTTP in isolated Docker.

Synthetic-only bearer authorization regression: the existing no-token Docker
gate proves project-scoped job IDs, but not that actual rendered MP4 bytes,
queue admission and polling stay private when a bearer token is configured.
No real credentials, owner footage, network, GPU, or paid services.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
from threading import Barrier
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
TOKEN = "SYNTHETIC_ONLY_HELPER1_BEARER_qa_20261024"


def run(*args: str) -> bytes:
    return subprocess.run(
        args, check=True, capture_output=True, timeout=120
    ).stdout


def api(method: str, path: str, payload: dict | None = None,
        auth: str = "valid", origin: str | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    if auth == "valid":
        headers["Authorization"] = "Bearer " + TOKEN
    elif auth == "wrong":
        headers["Authorization"] = "Bearer definitely-wrong"
    if origin is not None:
        headers["Origin"] = origin
    request = Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=20) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read()
    except HTTPError as error:
        return error.code, {k.lower(): v for k, v in error.headers.items()}, error.read()


def json_api(method: str, path: str, payload: dict | None = None,
             auth: str = "valid", origin: str | None = None):
    code, headers, body = api(method, path, payload, auth, origin)
    return code, headers, json.loads(body)


class AuthenticatedRealMediaDocker(unittest.TestCase):
    def test_real_master_requires_bearer_at_every_http_boundary(self):
        # The server is launched separately with exactly this *synthetic*
        # environment token. The container has --network none, no host mounts,
        # read-only root, and a disposable tmpfs workspace.
        private_prompt = "SYNTHETIC_PRIVATE_FILM_CANARY_bearer_20261024"
        created = service.create_project(models.ProjectCreateRequest(
            title="Offline bearer cinematic proof",
            master_prompt=private_prompt,
            target_duration_seconds=10,
            delivery_fps=24,
            delivery_resolution="480p",
            aspect_ratio="16:9",
            reference_image_ids=[],
        ))
        scene_id, shot_id, asset_id = uuid4().hex, uuid4().hex, uuid4().hex
        shot = models.CinematicShot(
            shot_id=shot_id, ordinal=1, title="Red slate",
            prompt="Synthetic red color", duration_seconds=10,
        )
        scene = models.CinematicScene(
            scene_id=scene_id, ordinal=1, title="Private synthetic",
            target_duration_seconds=10, shots=[shot],
        )
        project = service.update_project(
            created.id,
            models.ProjectUpdateRequest(expected_revision=1, scenes=[scene]),
        )
        source = storage.video_asset_path(asset_id, "mp4")
        run("ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi",
            "-i", "color=c=red:s=160x90:r=24:d=10", "-an",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(source))
        source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
        self.assertGreater(source.stat().st_size, 1024)
        record = storage.put_video_record("video_job", {
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
                        "latest_job_id": record["id"],
                        "latest_rendered_project_revision": 2,
                    }),
                ]})],
            ),
        )
        self.assertEqual(project.revision, 3)
        self.assertTrue(service.project_render_status(project.id)["ready_for_assembly"])

        root = f"/api/video/projects/{project.id}"
        queue = root + "/assembly-jobs"
        for auth in ("none", "wrong"):
            for method, path, payload in (
                ("GET", root, None),
                ("GET", queue, None),
                ("POST", queue, {"expected_revision": 3}),
            ):
                code, _, _ = api(method, path, payload, auth=auth)
                self.assertEqual(code, 401, (auth, method, path))
        code, _, _ = api("GET", root + "?token=" + TOKEN, auth="none")
        self.assertEqual(code, 401, "Query-string token must not authorize")
        self.assertFalse(storage.list_video_records("video_assembly_job"))

        # Even a valid bearer must not bypass a disallowed foreign write Origin.
        code, _, _ = api(
            "POST", queue, {"expected_revision": 3}, auth="valid",
            origin="https://cinema.attacker.invalid",
        )
        self.assertEqual(code, 403)
        self.assertFalse(storage.list_video_records("video_assembly_job"))

        # Eight real simultaneous authorized HTTP submissions model repeated
        # mobile taps/reconnects. All must share the one *active* durable
        # receipt rather than creating duplicate FFmpeg work. This uses the
        # actual HTTP server, SQLite admission and real assembly worker.
        callers = 8
        start = Barrier(callers)

        def admit(_index: int):
            start.wait(timeout=15)
            return json_api(
                "POST", queue, {"expected_revision": 3}, auth="valid"
            )

        with ThreadPoolExecutor(max_workers=callers) as pool:
            admissions = list(pool.map(admit, range(callers)))
        self.assertTrue(
            all(code == 202 for code, _, _ in admissions), admissions
        )
        receipts = [body for _, _, body in admissions]
        self.assertEqual(
            len({item["id"] for item in receipts}), 1,
            "Concurrent requests must not enqueue duplicate active work",
        )
        self.assertTrue(
            all(item["status"] in {"queued", "running"} for item in receipts),
            receipts,
        )
        self.assertEqual(
            len(storage.list_video_records("video_assembly_job")), 1,
            "One project/revision must have one durable active receipt",
        )
        receipt = receipts[0]
        self.assertNotIn(private_prompt, json.dumps(receipts))
        self.assertNotIn(TOKEN, json.dumps(receipts))
        job_url = queue + "/" + receipt["id"]
        for auth in ("none", "wrong"):
            self.assertEqual(api("GET", job_url, auth=auth)[0], 401)
            self.assertEqual(api("POST", job_url + "/cancel", auth=auth)[0], 401)

        deadline = time.monotonic() + 120
        while True:
            code, _, finished = json_api("GET", job_url)
            self.assertEqual(code, 200, finished)
            if finished["status"] in {"succeeded", "failed", "cancelled"}:
                break
            self.assertLess(time.monotonic(), deadline, "FFmpeg queue timed out")
            time.sleep(0.35)
        self.assertEqual(finished["status"], "succeeded", finished)
        self.assertTrue(finished["probe_metadata_verified"])
        self.assertNotIn(private_prompt, json.dumps(finished))
        self.assertNotIn(TOKEN, json.dumps(finished))
        self.assertEqual(
            storage.get_video_record("video_master", finished["master_id"])[
                "source_asset_hashes"
            ], [source_sha],
        )

        # These are the *real assembled* bytes, not mocked media metadata.
        asset_url = finished["asset_url"]
        for auth in ("none", "wrong"):
            self.assertEqual(api("GET", asset_url, auth=auth)[0], 401)
        self.assertEqual(
            api("GET", asset_url + "?token=" + TOKEN, auth="none")[0], 401
        )
        code, headers, media = api("GET", asset_url)
        self.assertEqual(code, 200)
        self.assertEqual(headers.get("cache-control"), "no-store")
        self.assertTrue(headers.get("content-type", "").startswith("video/mp4"))
        self.assertEqual(hashlib.sha256(media).hexdigest(), finished["sha256"])
        output = storage.video_asset_path(finished["asset_id"], "mp4")
        self.assertEqual(output.read_bytes(), media)
        probe = json.loads(run(
            "ffprobe", "-v", "error", "-show_streams", "-of", "json",
            str(output),
        ))
        videos = [s for s in probe["streams"] if s["codec_type"] == "video"]
        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]["codec_name"], "h264")
        self.assertEqual((videos[0]["width"], videos[0]["height"]), (854, 480))
        self.assertEqual(int(videos[0]["nb_frames"]), 240)
        run("ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i",
            str(output), "-an", "-f", "null", "-")

        # Regression: after the first real master completes, the source MP4
        # can change *without* changing its asset ID or project revision.
        # Concurrent authenticated retries must never return the old cached
        # master or publish multiple distinct masters for those new bytes.
        original_master_id = finished["master_id"]
        original_master_bytes = media
        run("ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi",
            "-i", "color=c=blue:s=160x90:r=24:d=10", "-an",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(source))
        refreshed_source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
        self.assertNotEqual(refreshed_source_sha, source_sha)
        self.assertEqual(service.get_project(project.id).revision, 3)

        retry_barrier = Barrier(callers)

        def refresh_admission(_index: int):
            retry_barrier.wait(timeout=15)
            return json_api("POST", queue, {"expected_revision": 3})

        with ThreadPoolExecutor(max_workers=callers) as pool:
            refresh_responses = list(pool.map(refresh_admission, range(callers)))
        self.assertTrue(
            all(code == 202 for code, _, _ in refresh_responses),
            refresh_responses,
        )
        refresh_receipts = [body for _, _, body in refresh_responses]
        self.assertEqual(
            len({item["id"] for item in refresh_receipts}), 1,
            "Concurrent refreshes must share one active assembly receipt",
        )
        self.assertNotEqual(refresh_receipts[0]["id"], receipt["id"])
        self.assertNotIn(private_prompt, json.dumps(refresh_receipts))
        self.assertNotIn(TOKEN, json.dumps(refresh_receipts))

        refresh_url = queue + "/" + refresh_receipts[0]["id"]
        deadline = time.monotonic() + 120
        while True:
            code, _, refreshed = json_api("GET", refresh_url)
            self.assertEqual(code, 200)
            if refreshed["status"] in {"succeeded", "failed", "cancelled"}:
                break
            self.assertLess(time.monotonic(), deadline, "Refresh timed out")
            time.sleep(0.35)
        self.assertEqual(refreshed["status"], "succeeded", refreshed)
        self.assertTrue(refreshed["probe_metadata_verified"])
        self.assertNotEqual(refreshed["master_id"], original_master_id)
        self.assertNotEqual(refreshed["sha256"], finished["sha256"])
        self.assertEqual(
            storage.get_video_record("video_master", refreshed["master_id"])[
                "source_asset_hashes"
            ], [refreshed_source_sha],
        )
        self.assertEqual(
            len(storage.list_video_records("video_master")), 2,
            "One historical and one refreshed master, not eight outputs",
        )
        self.assertEqual(output.read_bytes(), original_master_bytes)
        self.assertEqual(service.get_project(project.id).revision, 3)

        for auth in ("none", "wrong"):
            self.assertEqual(api("GET", refreshed["asset_url"], auth=auth)[0], 401)
        code, headers, refreshed_media = api("GET", refreshed["asset_url"])
        self.assertEqual(code, 200)
        self.assertEqual(headers.get("cache-control"), "no-store")
        self.assertEqual(
            hashlib.sha256(refreshed_media).hexdigest(), refreshed["sha256"]
        )
        refreshed_path = storage.video_asset_path(refreshed["asset_id"], "mp4")
        self.assertEqual(refreshed_path.read_bytes(), refreshed_media)
        refreshed_probe = json.loads(run(
            "ffprobe", "-v", "error", "-show_streams", "-of", "json",
            str(refreshed_path),
        ))
        refreshed_video = [
            stream for stream in refreshed_probe["streams"]
            if stream["codec_type"] == "video"
        ]
        self.assertEqual(len(refreshed_video), 1)
        self.assertEqual(refreshed_video[0]["codec_name"], "h264")
        self.assertEqual(int(refreshed_video[0]["nb_frames"]), 240)
        run("ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i",
            str(refreshed_path), "-an", "-f", "null", "-")
        center_pixel = run(
            "ffmpeg", "-nostdin", "-v", "error", "-ss", "5",
            "-i", str(refreshed_path), "-vf", "scale=1:1",
            "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"
        )
        self.assertEqual(len(center_pixel), 3)
        self.assertGreater(center_pixel[2], center_pixel[0] + 70)
        self.assertGreater(center_pixel[2], center_pixel[1] + 70)

        # Correct bearer is not an entitlement to poll another project ID.
        foreign = service.create_project(models.ProjectCreateRequest(
            title="Other synthetic project",
            master_prompt="SYNTHETIC_SECOND_PRIVATE_CANARY",
            target_duration_seconds=10, delivery_fps=24,
            delivery_resolution="480p", aspect_ratio="16:9",
            reference_image_ids=[],
        ))
        foreign_queue = f"/api/video/projects/{foreign.id}/assembly-jobs"
        self.assertEqual(
            api("GET", foreign_queue + "/" + receipt["id"])[0], 404
        )
        self.assertEqual(
            api("POST", foreign_queue + "/" + receipt["id"] + "/cancel")[0],
            404,
        )
        code, _, history = json_api("GET", foreign_queue)
        self.assertEqual(code, 200)
        self.assertEqual(history["jobs"], [])
        code, _, masters = json_api("GET", f"/api/video/projects/{foreign.id}/masters")
        self.assertEqual(code, 200)
        self.assertEqual(masters, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
