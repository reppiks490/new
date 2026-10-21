from __future__ import annotations

import json
import time

from PIL import Image

from app.video.models import EngineCapabilities, VideoGenerationRequest
from app.video.storage import get_video_record, put_video_record, video_asset_path

VALID_ID = "0123456789abcdef0123456789abcdef"


def _request(**changes):
    data = {
        "image_id": VALID_ID,
        "prompt": "private prompt text that must not be persisted",
        "engine_profile": "balanced",
        "seed": 7,
        "duration_seconds": 2,
        "fps": 24,
        "resolution": "720p",
    }
    data.update(changes)
    return VideoGenerationRequest(**data)


def _source():
    path = video_asset_path(VALID_ID, "png")
    Image.new("RGB", (48, 32), (15, 25, 35)).save(path)
    return path


def test_enqueue_video_job_runs_fake_engine_and_does_not_persist_prompt(monkeypatch, tmp_path):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    from app.video import engine, jobs

    engine._ENGINE_REGISTRY.clear()
    engine.register_engine(engine.FakeVideoEngine())
    _source()

    job = jobs.enqueue_video_job(_request())
    deadline = time.time() + 10
    while time.time() < deadline:
        stored = get_video_record("video_job", job["id"])
        if stored["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.05)
    else:
        raise AssertionError("video job did not finish")

    assert stored["status"] == "succeeded", stored
    assert stored["stage"] == "Ready"
    assert stored["progress"] == 100
    assert stored["asset_url"].endswith(".mp4")
    assert video_asset_path(stored["asset_id"], "mp4").is_file()
    assert "prompt" not in stored
    assert "private prompt text" not in json.dumps(stored)


def test_execute_video_job_records_expected_stage_sequence(monkeypatch, tmp_path):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    from app.video import engine, jobs

    engine._ENGINE_REGISTRY.clear()
    fake = engine.FakeVideoEngine()
    engine.register_engine(fake)
    _source()
    job_id = "1" * 32
    put_video_record(
        "video_job",
        {"status": "queued", "stage": "Queued", "progress": 0, "engine": fake.name},
        identifier=job_id,
    )
    seen = []
    original = jobs._update_job

    def recording_update(identifier, **changes):
        seen.append(changes.copy())
        return original(identifier, **changes)

    monkeypatch.setattr(jobs, "_update_job", recording_update)
    jobs.execute_video_job(job_id, _request(), fake.name)

    stages = [item.get("stage") for item in seen if "stage" in item]
    assert stages[0] == "Loading"
    assert "Generating" in stages
    assert "Encoding" in stages
    assert stages[-1] == "Ready"


def test_execute_video_job_redacts_secret_from_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("SOME_PRIVATE_TOKEN", "ultra-secret-token")
    from app.video import engine, jobs

    class FailingEngine:
        name = "failing"

        def capabilities(self):
            return EngineCapabilities(
                name=self.name,
                available=True,
                profiles=["balanced"],
                supported_resolutions=["720p"],
                supported_fps=[24],
            )

        def generate(self, *, request, source_path, output_path, progress):
            raise RuntimeError("failure ultra-secret-token")

    engine._ENGINE_REGISTRY.clear()
    bad = FailingEngine()
    engine.register_engine(bad)
    _source()
    job_id = "2" * 32
    put_video_record(
        "video_job",
        {"status": "queued", "stage": "Queued", "progress": 0, "engine": bad.name},
        identifier=job_id,
    )

    jobs.execute_video_job(job_id, _request(), bad.name)
    stored = get_video_record("video_job", job_id)

    assert stored["status"] == "failed"
    assert stored["stage"] == "Stopped"
    assert "ultra-secret-token" not in stored["error"]
    assert "[redacted]" in stored["error"]


def test_restart_interrupts_active_video_jobs_without_resubmission(monkeypatch, tmp_path):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    from app.video import jobs

    queued = put_video_record("video_job", {"status": "queued", "stage": "Queued", "progress": 0})
    running = put_video_record("video_job", {"status": "running", "stage": "Generating", "progress": 30})
    complete = put_video_record("video_job", {"status": "succeeded", "stage": "Ready", "progress": 100})

    assert jobs.interrupt_active_video_jobs() == 2
    assert get_video_record("video_job", queued["id"])["stage"] == "Interrupted"
    assert get_video_record("video_job", running["id"])["stage"] == "Interrupted"
    assert get_video_record("video_job", complete["id"])["status"] == "succeeded"
