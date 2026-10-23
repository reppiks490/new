"""QA-only project-library retention contract; synthetic metadata, no media or GPU.

A project remains individually readable after 101 are created, but the shared
100-record listing cap currently hides one from the project library. The test
is intentionally RED at the 101st project until a reviewed listing/pagination
fix exists; do not interpret RED as loss of the persisted project.
"""
from __future__ import annotations

import importlib

import pytest


@pytest.mark.parametrize("count", [100, 101], ids=["at_history_cap", "past_history_cap"])
def test_all_persisted_cinematic_projects_remain_discoverable(monkeypatch, tmp_path, count):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    storage = importlib.import_module("app.video.storage")

    created_ids = []
    for index in range(count):
        project = service.create_project(models.ProjectCreateRequest(
            title=f"Synthetic film {index:03d}",
            master_prompt="Synthetic, fictional continuity and scene blocking only.",
            target_duration_seconds=10,
            delivery_fps=24,
            delivery_resolution="480p",
            aspect_ratio="16:9",
        ))
        created_ids.append(project.id)

    # Direct SQLite-backed reads prove that no project was actually deleted.
    assert all(storage.get_video_record("video_project", identifier)["id"] == identifier
               for identifier in created_ids)
    visible_ids = {project.id for project in service.list_projects()}
    assert visible_ids == set(created_ids), (
        "A persisted cinematic project is hidden by the project-list history cap; "
        "provide a complete or explicitly paginated, discoverable project library"
    )
