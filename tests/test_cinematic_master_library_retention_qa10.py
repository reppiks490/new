"""QA-only master-library retention contract; synthetic SQLite metadata, no media.

The per-project GET /masters handler filters a globally capped list of the
newest 100 video_master records. After 101 total masters across projects, an
older master can remain persisted and directly readable yet disappear from
its own project's history. This is discoverability, not proven media loss.
"""
from __future__ import annotations

import importlib

import pytest


@pytest.mark.parametrize(
    "unrelated_newer",
    [98, 99],
    ids=["at_global_100_record_cap", "past_global_100_record_cap"],
)
def test_project_master_history_retains_older_masters_across_other_projects(
    monkeypatch, tmp_path, unrelated_newer,
):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    storage = importlib.import_module("app.video.storage")
    studio_storage = importlib.import_module("app.studio.storage")
    router = importlib.import_module("app.video.router")

    def make_project(title):
        return service.create_project(models.ProjectCreateRequest(
            title=title,
            master_prompt="Synthetic QA metadata; no private footage or real render.",
            target_duration_seconds=10,
            delivery_fps=24,
            delivery_resolution="480p",
            aspect_ratio="16:9",
        ))

    target = make_project("Synthetic target film")
    other = make_project("Synthetic unrelated film")

    # This test exercises record discovery ONLY. The metadata is deliberately
    # synthetic; it does not attest to real FFmpeg output or model inference.
    def master(project_id, serial):
        return storage.put_video_record("video_master", {
            "status": "ready",
            "project_id": project_id,
            "project_revision": 1,
            "source_digest": f"{serial:064x}",
            "asset_id": f"{serial + 1:032x}",
            "sha256": f"{serial + 2:064x}",
            "actual_video_probe_verified": False,
            "qa_synthetic_metadata_only": True,
        })

    oldest = master(target.id, 1)
    newest_target = master(target.id, 2)
    unrelated = [master(other.id, index + 10) for index in range(unrelated_newer)]

    # Set deterministic record ordering independent of host clock resolution.
    with studio_storage.connection() as db:
        for ordinal, record in enumerate([oldest, newest_target, *unrelated], start=1):
            db.execute(
                "UPDATE records SET updated=? WHERE kind='video_master' AND id=?",
                (float(ordinal), record["id"]),
            )

    assert storage.get_video_record("video_master", oldest["id"])["project_id"] == target.id
    assert storage.get_video_record("video_master", newest_target["id"])["project_id"] == target.id

    # The real route handler checks that the requested project exists before
    # filtering master records. Authentication middleware is NOT tested here.
    listed = router.cinematic_project_masters(target.id)
    listed_ids = {record["id"] for record in listed}
    assert all(record["project_id"] == target.id for record in listed), (
        "Other projects' master metadata must not appear in this project history"
    )
    assert newest_target["id"] in listed_ids
    assert oldest["id"] in listed_ids, (
        "An individually retrievable older master was silently hidden by the "
        "global 100-record list cap; add explicit per-project pagination or "
        "another complete discoverability contract"
    )
