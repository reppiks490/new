"""Opt-in Docker runtime acceptance for the cinematic studio, not the 3D API.

Execute *inside* an isolated container:
    docker exec -i cinematic-qa python - < tools/cinematic_docker_runtime_contract_helper1.py

Uses only loopback HTTP, synthetic color footage and temporary files. It does not
read owner workspaces, contact providers, create studio jobs, or require secrets.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

BASE = "http://127.0.0.1:8000"


def get_json(path: str) -> tuple[int, object]:
    try:
        with urlopen(BASE + path, timeout=8) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


class CinematicDockerRuntimeContract(unittest.TestCase):
    def test_studio_health_not_legacy_3d_health(self):
        status, body = get_json("/health")
        self.assertEqual(status, 200)
        self.assertIsInstance(body, dict)
        self.assertIs(body.get("studio"), True,
                      "Docker /health must identify the cinematic studio; "
                      "the generic Character3D API health is not cinematic acceptance")

    def test_private_cinematic_project_route_is_actually_served(self):
        # Request originates inside the container: genuine loopback peer and
        # literal 127.0.0.1 Host. No token or owner project data is supplied.
        status, body = get_json("/api/video/projects")
        self.assertEqual(status, 200,
                         "Docker must serve the cinematic private project API, "
                         "not just a generic /health route")
        self.assertIsInstance(body, (dict, list))

    def test_offline_real_ffmpeg_ffprobe_encode_probe_and_full_decode(self):
        self.assertIsNotNone(shutil.which("ffmpeg"),
                             "Cinematic Docker image lacks executable ffmpeg")
        self.assertIsNotNone(shutil.which("ffprobe"),
                             "Cinematic Docker image lacks executable ffprobe")
        with tempfile.TemporaryDirectory(prefix="cinematic-docker-qa-") as folder:
            output = Path(folder) / "synthetic-12-frame.mp4"
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                 "-f", "lavfi", "-i", "color=c=blue:s=64x64:r=12",
                 "-frames:v", "12", "-c:v", "libx264",
                 "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart",
                 str(output)],
                check=True, capture_output=True, text=True, timeout=40,
            )
            self.assertGreater(output.stat().st_size, 100)
            digest = hashlib.sha256(output.read_bytes()).hexdigest()
            self.assertEqual(len(digest), 64)
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-count_frames",
                 "-select_streams", "v:0",
                 "-show_entries", "stream=codec_name,width,height,nb_read_frames",
                 "-of", "json", str(output)],
                check=True, capture_output=True, text=True, timeout=20,
            )
            streams = json.loads(probe.stdout)["streams"]
            self.assertEqual(len(streams), 1)
            self.assertEqual(streams[0]["codec_name"], "h264")
            self.assertEqual((streams[0]["width"], streams[0]["height"]), (64, 64))
            self.assertEqual(int(streams[0]["nb_read_frames"]), 12)
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error",
                 "-i", str(output), "-f", "null", "-"],
                check=True, capture_output=True, text=True, timeout=30,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
