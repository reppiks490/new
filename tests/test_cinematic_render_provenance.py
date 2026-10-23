"""Versioned job provenance: real PNG bytes + creative intent, no GPU inference."""
from __future__ import annotations

import hashlib
import importlib
from pathlib import Path

import pytest
from PIL import Image

IMAGE_ID = "a" * 32
SCENE_ID = "b" * 32
SHOT_ID = "c" * 32


class CapturePool:
    def __init__(self):
        self.calls = []
    def submit(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return object()


def _ready(monkeypatch, tmp_path):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    service = importlib.import_module("app.video.cinematic_service")
    models = importlib.import_module("app.video.cinematic_models")
    storage = importlib.import_module("app.video.storage")
    requests = importlib.import_module("app.video.cinematic_requests")
    engine = importlib.import_module("app.video.engine")
    jobs = importlib.import_module("app.video.jobs")
    monkeypatch.setattr(engine, "_ENGINE_REGISTRY", {})
    engine.register_engine(engine.FakeVideoEngine())
    pool = CapturePool()
    monkeypatch.setattr(jobs, "pool", pool)
    path = storage.video_asset_path(IMAGE_ID, "png")
    Image.new("RGB", (20, 16), (11, 22, 33)).save(path)

    created = service.create_project(models.ProjectCreateRequest(
        title="Private credit roll",
        master_prompt="PRIVATE_STORY_UNSHARED",
        reference_image_ids=[IMAGE_ID],
        target_duration_seconds=10,
        delivery_fps=24,
        delivery_resolution="720p",
    ))
    shot = models.CinematicShot(
        shot_id=SHOT_ID, ordinal=1, title="Wide shot",
        prompt="PRIVATE_SHOT_CINEMATIC_MOVEMENT", duration_seconds=5,
    )
    scene = models.CinematicScene(
        scene_id=SCENE_ID, ordinal=1, title="Opening",
        shots=[shot], target_duration_seconds=5,
    )
    project = service.update_project(
        created.id, models.ProjectUpdateRequest(
            expected_revision=1, scenes=[scene],
        ),
    )
    return service, models, storage, requests, jobs, pool, path, project


def _enqueue_one(ctx):
    service, _, _, requests, _, _, _, project = ctx
    return service.render_project_missing(
        project.id,
        requests.BatchRenderRequest(
            expected_revision=project.revision, engine_name="fake", max_shots=1,
        ),
    )


def _complete(storage, jobs, record):
    asset_id = "d" * 32
    storage.video_asset_path(asset_id, "mp4").write_bytes(
        b"\x00\x00\x00\x18ftypmp42video"
    )
    jobs._update_job(
        record["id"], status="succeeded", stage="Ready",
        progress=100, asset_id=asset_id,
        asset_url=f"/api/video/assets/{asset_id}.mp4",
    )


def test_new_cinematic_job_persists_digest_without_private_inputs(monkeypatch, tmp_path):
    ctx = _ready(monkeypatch, tmp_path)
    service, _, storage, _, jobs, pool, _, project = ctx
    result = _enqueue_one(ctx)
    job = storage.get_video_record("video_job", result["jobs"][0]["id"])
    digest = job["render_intent_sha256"]
    assert len(digest) == 64
    assert all(ch in "0123456789abcdef" for ch in digest)
    assert hashlib.sha256(b"").hexdigest() != digest
    assert "PRIVATE_STORY_UNSHARED" not in str(job)
    assert "PRIVATE_SHOT_CINEMATIC_MOVEMENT" not in str(job)
    assert len(pool.calls) == 1
    assert job["engine"] == "fake"
    assert service.project_render_status(project.id)["active"] == 1

    _complete(storage, jobs, job)
    latest = service.project_render_status(project.id)
    assert latest["succeeded"] == 1
    assert latest["ready_for_assembly"] is True
    assert latest["legacy_unverified_shots"] == 0
    assert latest["ready_with_verified_render_provenance"] is True


def test_changed_png_bytes_same_reference_id_invalidates_success_and_retries(
    monkeypatch, tmp_path
):
    ctx = _ready(monkeypatch, tmp_path)
    service, _, storage, requests, jobs, pool, image, project = ctx
    scheduled = _enqueue_one(ctx)
    old = scheduled["jobs"][0]
    _complete(storage, jobs, old)
    assert service.project_render_status(project.id)["ready_for_assembly"]

    # Local trusted workspace image file changes but its 32-hex ID does not.
    Image.new("RGB", (20, 16), (99, 32, 8)).save(image)
    stale = service.project_render_status(project.id)
    assert stale["succeeded"] == 0
    assert stale["missing"] == 1
    assert stale["ready_for_assembly"] is False
    with pytest.raises(service.MasterAssemblyNotReady):
        service.assemble_project_master(
            project.id,
            requests.AssembleMasterRequest(expected_revision=3),
        )

    retry = service.render_project_missing(
        project.id,
        requests.BatchRenderRequest(expected_revision=3, engine_name="fake"),
    )
    assert len(retry["jobs"]) == 1
    assert retry["jobs"][0]["id"] != old["id"]
    assert retry["jobs"][0]["render_intent_sha256"] != old["render_intent_sha256"]
    assert len(pool.calls) == 2
    assert retry["project"]["revision"] == 4


def test_relinking_old_success_job_after_prompt_change_is_not_trusted(
    monkeypatch, tmp_path
):
    ctx = _ready(monkeypatch, tmp_path)
    service, models, storage, requests, jobs, pool, _, project = ctx
    old = _enqueue_one(ctx)["jobs"][0]
    _complete(storage, jobs, old)

    old_project = service.get_project(project.id)
    scene = old_project.scenes[0]
    updated = scene.shots[0].model_copy(update={
        "prompt": "BRAND_NEW_CREATIVE_INSTRUCTIONS",
    })
    edited = service.update_project(project.id, models.ProjectUpdateRequest(
        expected_revision=old_project.revision,
        scenes=[scene.model_copy(update={"shots": [updated]})],
    ))
    assert edited.scenes[0].shots[0].latest_job_id is None

    forged = edited.scenes[0].shots[0].model_copy(update={
        "latest_job_id": old["id"],
        "latest_asset_url": f"/api/video/assets/{'d' * 32}.mp4",
    })
    forged_project = service.update_project(
        project.id, models.ProjectUpdateRequest(
            expected_revision=edited.revision,
            scenes=[edited.scenes[0].model_copy(update={"shots": [forged]})],
        ),
    )
    # A copied job link is present in the document, but provenance gates
    # refuse to mark a previous creative version as current.
    assert forged_project.scenes[0].shots[0].latest_job_id == old["id"]
    state = service.project_render_status(project.id)
    assert state["missing"] == 1
    assert state["succeeded"] == 0
    assert state["ready_for_assembly"] is False

    with pytest.raises(service.MasterAssemblyNotReady):
        service.assemble_project_master(
            project.id, requests.AssembleMasterRequest(
                expected_revision=forged_project.revision,
            ),
        )
    fixed = service.render_project_missing(
        project.id,
        requests.BatchRenderRequest(
            expected_revision=forged_project.revision,
            engine_name="fake",
        ),
    )
    assert len(fixed["jobs"]) == 1
    assert fixed["jobs"][0]["id"] != old["id"]
    assert len(pool.calls) == 2


def test_title_only_edit_preserves_same_digest_and_completed_shot(
    monkeypatch, tmp_path
):
    ctx = _ready(monkeypatch, tmp_path)
    service, models, storage, _, jobs, _, _, project = ctx
    old = _enqueue_one(ctx)["jobs"][0]
    _complete(storage, jobs, old)
    before = service.get_project(project.id)
    revised = service.update_project(project.id, models.ProjectUpdateRequest(
        expected_revision=before.revision,
        title="New editor-visible name",
    ))
    assert revised.scenes[0].shots[0].latest_job_id == old["id"]
    assert service.project_render_status(project.id)["ready_for_assembly"] is True


def test_missing_source_png_fails_closed_for_modern_link_without_new_job(
    monkeypatch, tmp_path
):
    ctx = _ready(monkeypatch, tmp_path)
    service, _, storage, _, jobs, pool, image, project = ctx
    old = _enqueue_one(ctx)["jobs"][0]
    _complete(storage, jobs, old)
    image.unlink()
    state = service.project_render_status(project.id)
    assert (state["missing"], state["succeeded"]) == (1, 0)
    assert state["ready_for_assembly"] is False
    assert len(pool.calls) == 1


@pytest.mark.parametrize("bad", [None, "", "123", "A"*64, "f"*65, True])
def test_job_metadata_rejects_invalid_provenance_hash(bad):
    jobs = importlib.import_module("app.video.jobs")
    with pytest.raises(ValueError, match="render_intent_sha256"):
        jobs._safe_metadata({"render_intent_sha256": bad})


def test_same_png_is_hashed_once_per_bounded_status_operation(monkeypatch, tmp_path):
    ctx = _ready(monkeypatch, tmp_path)
    service, _, storage, _, jobs, _, _, project = ctx
    old = _enqueue_one(ctx)["jobs"][0]
    _complete(storage, jobs, old)
    image_hash_calls = []
    original = service.hashlib.file_digest

    def counting_digest(fileobj, algorithm):
        image_hash_calls.append(Path(fileobj.name).suffix)
        return original(fileobj, algorithm)

    monkeypatch.setattr(service.hashlib, "file_digest", counting_digest)
    state = service.project_render_status(project.id)
    assert state["ready_for_assembly"]
    assert image_hash_calls.count(".png") == 1



def test_many_shots_reuse_one_image_hash_per_status(monkeypatch, tmp_path):
    """No per-shot redundant hash of a shared image on a long film status read."""
    ctx = _ready(monkeypatch, tmp_path)
    service, models, storage, _, _, _, _, project = ctx
    shots = [
        models.CinematicShot(
            shot_id=f"{index + 1:032x}", ordinal=index + 1,
            title=f"Camera angle {index + 1}",
            prompt=f"Action beat {index + 1}", duration_seconds=5,
        )
        for index in range(120)
    ]
    scene = models.CinematicScene(
        scene_id=SCENE_ID, ordinal=1, title="Long-form scene",
        shots=shots, target_duration_seconds=600,
    )
    adjusted = service.update_project(
        project.id, models.ProjectUpdateRequest(
            expected_revision=project.revision,
            target_duration_seconds=600,
            scenes=[scene],
        ),
    )
    linked = []
    for shot in adjusted.scenes[0].shots:
        digest = service._shot_render_provenance_digest(
            adjusted, adjusted.scenes[0], shot,
            engine_name="fake", native_fps=24, native_resolution="720p",
        )
        job = storage.put_video_record("video_job", {
            "project_id": adjusted.id,
            "scene_id": SCENE_ID,
            "shot_id": shot.shot_id,
            "engine": "fake",
            "fps": 24,
            "resolution": "720p",
            "status": "succeeded",
            "asset_id": "d" * 32,
            "render_intent_sha256": digest,
        })
        linked.append(shot.model_copy(update={"latest_job_id": job["id"]}))
    storage.video_asset_path("d" * 32, "mp4").write_bytes(
        b"\x00\x00\x00\x18ftypmp42test"
    )
    service.update_project(
        adjusted.id,
        models.ProjectUpdateRequest(
            expected_revision=adjusted.revision,
            scenes=[adjusted.scenes[0].model_copy(update={"shots": linked})],
        ),
    )
    real_digest = service.hashlib.file_digest
    image_reads = []

    def tracked_digest(fileobj, algorithm):
        if Path(fileobj.name).suffix == ".png":
            image_reads.append(fileobj.name)
        return real_digest(fileobj, algorithm)

    monkeypatch.setattr(service.hashlib, "file_digest", tracked_digest)
    state = service.project_render_status(adjusted.id)
    assert state["total_shots"] == 120
    assert state["succeeded"] == 120
    assert state["missing_output_assets"] == 0
    assert state["ready_for_assembly"] is True
    assert len(image_reads) == 1



def test_legacy_job_remains_readable_but_is_not_reported_as_provenance_verified(
    monkeypatch, tmp_path
):
    ctx = _ready(monkeypatch, tmp_path)
    service, models, storage, _, _, _, _, project = ctx
    storage.video_asset_path("d" * 32, "mp4").write_bytes(
        b"\x00\x00\x00\x18ftypmp42legacy"
    )
    prior = storage.put_video_record("video_job", {
        "status": "succeeded",
        "project_id": project.id,
        "scene_id": SCENE_ID,
        "shot_id": SHOT_ID,
        "asset_id": "d" * 32,
    })
    scene = project.scenes[0]
    linked = scene.shots[0].model_copy(update={"latest_job_id": prior["id"]})
    service.update_project(
        project.id,
        models.ProjectUpdateRequest(
            expected_revision=project.revision,
            scenes=[scene.model_copy(update={"shots": [linked]})],
        ),
    )
    state = service.project_render_status(project.id)
    assert state["succeeded"] == 1
    assert state["ready_for_assembly"] is True  # historical API compatibility
    assert state["legacy_unverified_shots"] == 1
    assert state["ready_with_verified_render_provenance"] is False
