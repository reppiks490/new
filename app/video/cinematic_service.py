from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from app.video.cinematic_models import (
    CinematicProject,
    CinematicScene,
    CinematicShot,
    ContinuityState,
    ProjectCreateRequest,
    ProjectUpdateRequest,
    merge_continuity,
)
from app.video.storage import (
    compare_and_swap_video_project,
    get_video_record,
    list_video_records,
    put_video_record,
    video_asset_path,
)


class ProjectRevisionConflict(RuntimeError):
    def __init__(self, project_id: str, expected_revision: int, actual_revision: int):
        self.project_id = project_id
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision
        super().__init__(
            f'Project {project_id} revision conflict: expected {expected_revision}, actual {actual_revision}'
        )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _project_payload(project: CinematicProject) -> dict:
    return project.model_dump(mode='json', exclude={'id'})


def create_project(request: ProjectCreateRequest) -> CinematicProject:
    now = _utcnow()
    project = CinematicProject(
        revision=1,
        title=request.title,
        master_prompt=request.master_prompt,
        target_duration_seconds=request.target_duration_seconds,
        delivery_fps=request.delivery_fps,
        delivery_resolution=request.delivery_resolution,
        aspect_ratio=request.aspect_ratio,
        continuity_bible=request.continuity_bible,
        reference_image_ids=request.reference_image_ids,
        scenes=[],
        created_at=now,
        updated_at=now,
    )
    record = put_video_record('video_project', _project_payload(project))
    return CinematicProject.model_validate(record)


def get_project(project_id: str) -> CinematicProject:
    return CinematicProject.model_validate(get_video_record('video_project', project_id))


def list_projects() -> list[CinematicProject]:
    return [CinematicProject.model_validate(record) for record in list_video_records('video_project')]


def update_project(project_id: str, request: ProjectUpdateRequest) -> CinematicProject:
    current = get_project(project_id)
    if current.revision != request.expected_revision:
        raise ProjectRevisionConflict(project_id, request.expected_revision, current.revision)

    patch = request.model_dump(mode='python', exclude={'expected_revision'}, exclude_none=True)
    data = current.model_dump(mode='python', exclude={'id'})
    data.update(patch)
    data['revision'] = current.revision + 1
    data['updated_at'] = _utcnow()
    candidate = CinematicProject.model_validate(data)
    payload = _project_payload(candidate)

    updated, actual_revision, record = compare_and_swap_video_project(
        project_id,
        expected_revision=request.expected_revision,
        data=payload,
    )
    if not updated or record is None:
        raise ProjectRevisionConflict(project_id, request.expected_revision, actual_revision)
    return CinematicProject.model_validate(record)


def resolve_effective_continuity(
    project: CinematicProject,
    scene: CinematicScene,
    shot: CinematicShot,
) -> ContinuityState:
    scene_state = merge_continuity(project.continuity_bible, scene.continuity_patch)
    return merge_continuity(scene_state, shot.continuity_patch)


def _ordered_unique(groups: Iterable[Iterable[str]]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for group in groups:
        for identifier in group:
            if identifier not in seen:
                seen.add(identifier)
                ordered.append(identifier)
    return ordered


def resolve_reference_ids(
    project: CinematicProject,
    scene: CinematicScene,
    shot: CinematicShot,
    *,
    require_assets: bool = True,
) -> list[str]:
    identifiers = _ordered_unique(
        (project.reference_image_ids, scene.reference_image_ids, shot.reference_image_ids)
    )
    if require_assets:
        for identifier in identifiers:
            path = video_asset_path(identifier, 'png')
            if not path.is_file():
                raise FileNotFoundError(f'Reference image {identifier} was not found')
    return identifiers


def find_scene(project: CinematicProject, scene_id: str) -> CinematicScene:
    for scene in project.scenes:
        if scene.scene_id == scene_id:
            return scene
    raise KeyError(scene_id)


def find_shot(scene: CinematicScene, shot_id: str) -> CinematicShot:
    for shot in scene.shots:
        if shot.shot_id == shot_id:
            return shot
    raise KeyError(shot_id)
