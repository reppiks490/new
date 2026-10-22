"""Independent QA for the asynchronous cinematic master-assembly API.

Verifies owner bearer authorization, origin rejection, project namespace isolation,
and private metadata without running FFmpeg or creating synthetic video outputs.
This is the QA lane; queue implementation remains owned by the assembly lead.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient


SCENE = "2" * 32
SHOT = "3" * 32
BEARER = "qa-private-bearer"
SECRET_MARKER = "SECRET_SCREENPLAY_DO_NOT_EXPOSE"


class HoldingPool:
    def submit(self, fn, *args, **kwargs):
        return object()


def _make_ready_project(models, service, storage, marker):
    project = service.create_project(models.ProjectCreateRequest(
        title="Private slate",
        master_prompt=f"{marker}: secret individual screenplay",
        target_duration_seconds=10,
        delivery_fps=24,
        delivery_resolution="480p",
        aspect_ratio="16:9",
    ))
    shot = models.CinematicShot(
        shot_id=SHOT, ordinal=1, title="Private shot",
        prompt="Private motion choreography", duration_seconds=2,
    )
    scene = models.CinematicScene(
        scene_id=SCENE, ordinal=1, title="Private scene",
        target_duration_seconds=2, shots=[shot],
    )
    project = service.update_project(
        project.id, models.ProjectUpdateRequest(expected_revision=1, scenes=[scene])
    )
    asset_id = "4" * 32
    storage.video_asset_path(asset_id, "mp4").write_bytes(
        b"\x00\x00\x00\x18ftypmp42private_qa"
    )
    video_job = storage.put_video_record("video_job", {
        "status": "succeeded", "project_id": project.id,
        "scene_id": SCENE, "shot_id": SHOT,
        "asset_id": asset_id, "project_revision": 2,
    })
    project = service.update_project(
        project.id,
        models.ProjectUpdateRequest(
            expected_revision=2,
            scenes=[scene.model_copy(update={"shots": [
                shot.model_copy(update={"latest_job_id": video_job["id"]})
            ]})],
        ),
    )
    assert service.project_render_status(project.id)["ready_for_assembly"]
    return project


def test_async_master_api_rejects_cross_origin_missing_bearer_and_cross_project_leaks(
    monkeypatch, tmp_path: Path
):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("CHARACTER3D_STUDIO_TOKEN", BEARER)
    monkeypatch.setenv("CHARACTER3D_STUDIO_ORIGINS", "")
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    storage = importlib.import_module("app.video.storage")
    queue = importlib.import_module("app.video.cinematic_assembly_jobs")
    monkeypatch.setattr(queue, "assembly_pool", HoldingPool())

    first = _make_ready_project(models, service, storage, SECRET_MARKER)
    second = _make_ready_project(models, service, storage, "SECOND_SECRET_FILM")
    for module in ("app.studio.server", "app.video.router"):
        sys.modules.pop(module, None)
    server = importlib.import_module("app.studio.server")

    url1 = f"/api/video/projects/{first.id}/assembly-jobs"
    url2 = f"/api/video/projects/{second.id}/assembly-jobs"
    auth = {"Authorization": f"Bearer {BEARER}"}

    with TestClient(server.app) as client:
        for method, url in (("POST", url1), ("GET", url1), ("GET", url2)):
            denied = client.request(method, url, json={"expected_revision": 3}
                                    if method == "POST" else None)
            assert denied.status_code == 401, denied.text
            assert SECRET_MARKER not in denied.text

        foreign = client.post(
            url1, json={"expected_revision": 3},
            headers={**auth, "Origin": "https://foreign.invalid"},
        )
        assert foreign.status_code == 403, foreign.text
        assert queue.list_master_assembly_jobs(first.id)["total"] == 0

        wrong_token = client.post(
            url1, json={"expected_revision": 3},
            headers={"Authorization": "Bearer incorrect"},
        )
        assert wrong_token.status_code == 401
        assert queue.list_master_assembly_jobs(first.id)["total"] == 0

        queued = client.post(url1, json={"expected_revision": 3}, headers=auth)
        assert queued.status_code == 202, queued.text
        job = queued.json()
        assert job["project_id"] == first.id
        assert job["status"] == "queued"
        assert "prompt" not in str(job).lower()
        assert SECRET_MARKER not in str(job)

        for path in (url1, f"{url1}/{job['id']}"):
            denied = client.get(path, params={"token": BEARER})
            assert denied.status_code == 401
            assert SECRET_MARKER not in denied.text
        own_detail = client.get(f"{url1}/{job['id']}", headers=auth)
        assert own_detail.status_code == 200, own_detail.text
        assert own_detail.json()["id"] == job["id"]
        cross_detail = client.get(f"{url2}/{job['id']}", headers=auth)
        assert cross_detail.status_code == 404, cross_detail.text
        other_list = client.get(url2, headers=auth)
        assert other_list.status_code == 200
        assert other_list.json()["jobs"] == []
        assert other_list.json()["total"] == 0

        for path in (url1, url2):
            listed = client.get(path, headers=auth)
            assert listed.status_code == 200
            assert SECRET_MARKER not in listed.text
            assert "SECOND_SECRET_FILM" not in listed.text
            assert BEARER not in listed.text

        assert queue.list_master_assembly_jobs(first.id)["total"] == 1


def test_async_master_api_invalid_pagination_does_not_expose_private_data(
    monkeypatch, tmp_path: Path
):
    monkeypatch.setenv("CHARACTER3D_STUDIO_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("CHARACTER3D_STUDIO_TOKEN", BEARER)
    monkeypatch.setenv("CHARACTER3D_STUDIO_ORIGINS", "")
    models = importlib.import_module("app.video.cinematic_models")
    service = importlib.import_module("app.video.cinematic_service")
    storage = importlib.import_module("app.video.storage")
    _make_ready_project(models, service, storage, SECRET_MARKER)
    project = service.list_projects()[0]
    for module in ("app.studio.server", "app.video.router"):
        sys.modules.pop(module, None)
    server = importlib.import_module("app.studio.server")
    route = f"/api/video/projects/{project.id}/assembly-jobs"
    auth = {"Authorization": f"Bearer {BEARER}"}

    with TestClient(server.app) as client:
        for args in ({"limit": 0}, {"limit": 201}, {"offset": -1}):
            invalid = client.get(route, params=args, headers=auth)
            assert invalid.status_code in {404, 422}, invalid.text
            assert SECRET_MARKER not in invalid.text
            assert BEARER not in invalid.text
        valid = client.get(route, params={"limit": 200, "offset": 0}, headers=auth)
        assert valid.status_code == 200
        assert valid.json()["total"] == 0
