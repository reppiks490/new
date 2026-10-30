from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.video.cinematic_models import CinematicProject, CinematicScene, CinematicShot, ProjectCreateRequest, ProjectUpdateRequest
from app.video import cinematic_service as service
from app.video.cinematic_requests import AssembleMasterRequest, BatchRenderRequest, CompileProjectRequest


def project_payload(seconds=600):
    return dict(title='Film', master_prompt='A character walks through a room.', target_duration_seconds=seconds, delivery_fps=120, delivery_resolution='2160p', aspect_ratio='16:9')


def legacy_project(*, target=601, shot_seconds=30, shots=21):
    now=datetime.now(timezone.utc)
    return CinematicProject(id='a'*32, revision=1, **project_payload(target), created_at=now, updated_at=now,
        scenes=[CinematicScene(scene_id='b'*32, ordinal=1, title='Scene', target_duration_seconds=max(1,shot_seconds*shots),
            shots=[CinematicShot(shot_id=f'{index+1:032x}', ordinal=index+1, title='Shot', prompt='Walk forward.', duration_seconds=shot_seconds) for index in range(shots)])])


def test_create_and_update_reject_duration_over_ten_minutes():
    assert ProjectCreateRequest(**project_payload()).target_duration_seconds == 600
    with pytest.raises(ValidationError):
        ProjectCreateRequest(**project_payload(600.001))
    with pytest.raises(ValidationError):
        ProjectUpdateRequest(expected_revision=1,target_duration_seconds=601)


def test_actual_edited_timeline_is_limited_even_when_target_is_valid(monkeypatch,tmp_path):
    monkeypatch.setenv('CHARACTER3D_STUDIO_WORKSPACE',str(tmp_path))
    project=service.create_project(ProjectCreateRequest(**project_payload(600)))
    scenes=legacy_project(target=600).scenes
    with pytest.raises(ValueError,match='600'):
        service.update_project(project.id,ProjectUpdateRequest(expected_revision=1,scenes=scenes))
    assert service.get_project(project.id).revision == 1


@pytest.mark.parametrize('operation', ['compile','batch','master'])
def test_legacy_overlong_project_is_blocked_before_any_work(monkeypatch,operation):
    project=legacy_project()
    monkeypatch.setattr(service,'get_project',lambda identifier:project)
    with pytest.raises(ValueError,match='600'):
        if operation == 'compile': service.compile_project(project.id,CompileProjectRequest(expected_revision=1))
        elif operation == 'batch': service.render_project_missing(project.id,BatchRenderRequest(expected_revision=1))
        else: service.assemble_project_master(project.id,AssembleMasterRequest(expected_revision=1))


def test_legacy_documents_remain_readable_for_explicit_shortening():
    project=legacy_project()
    assert CinematicProject.model_validate(project.model_dump()).target_duration_seconds == 601


def test_legacy_async_master_queue_rejects_overlong_project_before_writing(monkeypatch):
    from app.video import cinematic_assembly_jobs as queue
    monkeypatch.setattr(queue,'get_project',lambda identifier:legacy_project())
    monkeypatch.setattr(queue,'_dispatch',lambda:pytest.fail('should not dispatch'))
    with pytest.raises(service.FilmDurationExceeded,match='600'):
        queue.enqueue_master_assembly('a'*32,AssembleMasterRequest(expected_revision=1))
