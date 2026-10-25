"""QA48: real synthetic FFmpeg master survives an offline cinematic Docker restart.

Two modes use the same mounted SQLite/media workspace. 'prepare' creates a
synthetic project, sources, and deliberately persisted queue records WITHOUT
calling the dispatcher. 'verify' runs after an actual container restart and
checks startup recovery through the real HTTP API and FFmpeg. 'verify-stable'
checks a second restart does not re-encode a terminal master.

The 'running' record is synthetic, NOT evidence that an FFmpeg subprocess was
actually interrupted. Never use owner footage, credentials, or a live workspace.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen
from uuid import uuid4

from app.video import cinematic_models as models
from app.video import cinematic_service as service
from app.video import storage

BASE = "http://127.0.0.1:8000"
STATE = Path("/app/workspace/studio/qa48-synthetic-ids.json")
CANARY = "QA48_SYNTHETIC_PRIVATE_SCRIPT_DO_NOT_ECHO"


def run(*args: str, timeout: int = 120) -> bytes:
    return subprocess.run(list(args), capture_output=True, check=True, timeout=timeout).stdout


def synthetic_clip(path: Path, color: str, fps: int) -> None:
    run("ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi",
        "-i", f"color=c={color}:s=160x90:r={fps}:d=5",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(path))
    assert path.is_file() and path.stat().st_size > 128


def get_json(path: str) -> dict:
    with urlopen(BASE + path, timeout=15) as response:
        assert response.status == 200
        # Queue JSON no-store is a separate open privacy proposal (#78).
        raw = response.read()
    assert CANARY.encode() not in raw
    return json.loads(raw)


def prepare() -> None:
    assert not STATE.exists(), "QA48 workspace must be fresh"
    created = service.create_project(models.ProjectCreateRequest(
        title="Synthetic restart recovery",
        master_prompt=CANARY,
        target_duration_seconds=10,
        delivery_fps=24,
        delivery_resolution="480p",
        aspect_ratio="16:9",
        reference_image_ids=[],
    ))
    scene_id = uuid4().hex
    shots = [
        models.CinematicShot(shot_id=uuid4().hex, ordinal=i + 1,
            title=f"Synthetic {i+1}", prompt="color bars",
            duration_seconds=5)
        for i in range(2)
    ]
    scene = models.CinematicScene(
        scene_id=scene_id, ordinal=1, title="Synthetic scene",
        target_duration_seconds=10, shots=shots,
    )
    project = service.update_project(
        created.id, models.ProjectUpdateRequest(expected_revision=1, scenes=[scene])
    )
    linked = []
    for index, (color, fps) in enumerate((("red", 24), ("blue", 30))):
        asset_id = uuid4().hex
        synthetic_clip(storage.video_asset_path(asset_id, "mp4"), color, fps)
        record = storage.put_video_record("video_job", {
            "status": "succeeded", "stage": "Ready", "progress": 100,
            "project_id": project.id, "scene_id": scene_id,
            "shot_id": shots[index].shot_id, "project_revision": 2,
            "asset_id": asset_id,
            "asset_url": f"/api/video/assets/{asset_id}.mp4",
        })
        linked.append(shots[index].model_copy(update={
            "latest_job_id": record["id"],
            "latest_rendered_project_revision": 2,
        }))
    project = service.update_project(
        project.id, models.ProjectUpdateRequest(
            expected_revision=2,
            scenes=[scene.model_copy(update={"shots": linked})],
        ),
    )
    assert project.revision == 3
    assert service.project_render_status(project.id)["ready_for_assembly"]
    now = time.time()
    common = {
        "project_id": project.id, "project_revision": 3,
        "ffmpeg_path": "ffmpeg", "created_at": now,
        "updated_at": now,
    }
    # Directly seed durable rows to test startup recovery independently of
    # HTTP admission. No actual FFmpeg subprocess is interrupted here.
    interrupted = storage.put_video_record("video_assembly_job", {
        **common, "status": "running", "stage": "Assembling",
        "progress": None, "started_at": now - 2,
    })
    queued = storage.put_video_record("video_assembly_job", {
        **common, "status": "queued", "stage": "Queued", "progress": 0,
    })
    STATE.write_text(json.dumps({
        "project_id": project.id,
        "interrupted_id": interrupted["id"],
        "queued_id": queued["id"],
    }), encoding="utf-8")
    STATE.chmod(0o600)
    assert storage.get_video_record("video_assembly_job", queued["id"])["status"] == "queued"
    assert storage.get_video_record("video_assembly_job", interrupted["id"])["status"] == "running"
    print("QA48 PREPARED: synthetic SQLite running + queued rows and two FFmpeg clips")


def verify(stable: bool = False) -> None:
    ids = json.loads(STATE.read_text(encoding="utf-8"))
    project_id = ids["project_id"]
    prefix = f"/api/video/projects/{project_id}/assembly-jobs/"
    deadline = time.monotonic() + 150
    while True:
        interrupted = get_json(prefix + ids["interrupted_id"])
        queued = get_json(prefix + ids["queued_id"])
        if interrupted["status"] == "failed" and queued["status"] in {
            "succeeded", "failed", "cancelled",
        }:
            break
        assert time.monotonic() < deadline, "QA48 startup recovery timed out"
        time.sleep(0.4)
    assert interrupted["stage"] == "Interrupted", interrupted["stage"]
    assert queued["status"] == "succeeded", queued["stage"]
    assert queued["probe_metadata_verified"] is True
    assert service.get_project(project_id).revision == 3
    masters = storage.list_video_records("video_master")
    assert len(masters) == 1, "A restart must not duplicate the master"
    master = masters[0]
    assert master["id"] == queued["master_id"]
    assert master["project_id"] == project_id
    assert master["project_revision"] == 3
    output = storage.video_asset_path(queued["asset_id"], "mp4")
    media = output.read_bytes()
    digest = hashlib.sha256(media).hexdigest()
    assert digest == queued["sha256"] == master["sha256"]
    with urlopen(BASE + queued["asset_url"], timeout=20) as response:
        assert response.status == 200
        assert response.headers.get("Cache-Control") == "no-store"
        assert response.read() == media
    probe = json.loads(run(
        "ffprobe", "-v", "error", "-show_entries",
        "stream=codec_name,nb_frames,width,height:format=duration",
        "-select_streams", "v:0", "-of", "json", str(output),
    ))
    stream = probe["streams"][0]
    assert stream["codec_name"] == "h264"
    assert (stream["width"], stream["height"]) == (854, 480)
    assert int(stream["nb_frames"]) == 240
    assert abs(float(probe["format"]["duration"]) - 10) < 0.25
    run("ffmpeg", "-nostdin", "-v", "error", "-xerror",
        "-i", str(output), "-an", "-f", "null", "-")
    if stable:
        previous = json.loads((STATE.parent / "qa48-master-receipt.json").read_text())
        assert previous == {"id": master["id"], "sha256": digest}
    else:
        receipt = STATE.parent / "qa48-master-receipt.json"
        receipt.write_text(json.dumps({"id": master["id"], "sha256": digest}))
        receipt.chmod(0o600)
    print("QA48 VERIFIED: actual startup recovery, private HTTP, SHA, 240-frame full decode"
          + (", second restart stable" if stable else ""))


if __name__ == "__main__":
    assert len(sys.argv) == 2 and sys.argv[1] in {
        "prepare", "verify", "verify-stable",
    }
    if sys.argv[1] == "prepare":
        prepare()
    else:
        verify(stable=sys.argv[1] == "verify-stable")
