from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from app.video.cinematic_models import (
    CinematicProject,
    CinematicScene,
    CinematicShot,
    ContinuityState,
    DeliveryResolution,
    ProjectCreateRequest,
    ProjectUpdateRequest,
    RenderPlan,
    merge_continuity,
)
from app.video.models import EngineCapabilities
from app.video.storage import (
    compare_and_swap_video_project,
    get_video_record,
    list_video_records,
    put_video_record,
    video_asset_path,
)


_RESOLUTION_HEIGHT = {
    '480p': 480,
    '720p': 720,
    '1080p': 1080,
    '1440p': 1440,
    '2160p': 2160,
}


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


def select_native_fps(delivery_fps: int, supported_fps: list[int]) -> int:
    if not supported_fps:
        raise ValueError('engine declares no supported FPS values')
    supported = sorted(set(int(value) for value in supported_fps))
    at_or_below = [value for value in supported if value <= delivery_fps]
    return max(at_or_below) if at_or_below else min(supported)


def select_native_resolution(
    delivery_resolution: DeliveryResolution,
    supported_resolutions: list[str],
) -> DeliveryResolution:
    if not supported_resolutions:
        raise ValueError('engine declares no supported resolutions')
    invalid = [value for value in supported_resolutions if value not in _RESOLUTION_HEIGHT]
    if invalid:
        raise ValueError(f'engine declares unsupported resolution labels: {invalid!r}')
    target = _RESOLUTION_HEIGHT[delivery_resolution]
    supported = sorted(set(supported_resolutions), key=_RESOLUTION_HEIGHT.__getitem__)
    at_or_below = [value for value in supported if _RESOLUTION_HEIGHT[value] <= target]
    chosen = max(at_or_below, key=_RESOLUTION_HEIGHT.__getitem__) if at_or_below else supported[0]
    return chosen  # type: ignore[return-value]


def build_render_plan_from_objects(
    project: CinematicProject,
    scene: CinematicScene,
    shot: CinematicShot,
    capabilities: EngineCapabilities,
    *,
    require_assets: bool = True,
) -> RenderPlan:
    if project.id is None:
        raise ValueError('project must have a persisted id before rendering')
    if not capabilities.available:
        raise RuntimeError(f'engine {capabilities.name!r} is not available')
    if shot.engine_profile not in capabilities.profiles:
        raise ValueError(f'engine profile {shot.engine_profile!r} is not supported by {capabilities.name}')
    if not capabilities.min_duration_seconds <= shot.duration_seconds <= capabilities.max_duration_seconds:
        raise ValueError(
            f'shot duration {shot.duration_seconds} is outside engine range '
            f'{capabilities.min_duration_seconds}..{capabilities.max_duration_seconds}'
        )
    if shot.motion_strength is not None and not capabilities.supports_motion_strength:
        raise ValueError(f'motion_strength is not supported by {capabilities.name}')
    if shot.camera_motion is not None and shot.camera_motion not in capabilities.camera_motion_presets:
        raise ValueError(f'camera_motion {shot.camera_motion!r} is not supported by {capabilities.name}')

    references = resolve_reference_ids(project, scene, shot, require_assets=require_assets)
    continuity = resolve_effective_continuity(project, scene, shot)
    generation_fps = select_native_fps(project.delivery_fps, capabilities.supported_fps)
    generation_resolution = select_native_resolution(
        project.delivery_resolution,
        list(capabilities.supported_resolutions),
    )
    return RenderPlan(
        project_id=project.id,
        project_revision=project.revision,
        scene_id=scene.scene_id,
        shot_id=shot.shot_id,
        engine_name=capabilities.name,
        engine_profile=shot.engine_profile,
        prompt=shot.prompt,
        negative_prompt=shot.negative_prompt,
        effective_continuity=continuity,
        reference_image_ids=references,
        source_image_id=references[0] if references else None,
        duration_seconds=shot.duration_seconds,
        seed=shot.seed,
        motion_strength=shot.motion_strength,
        camera_motion=shot.camera_motion,
        generation_fps=generation_fps,
        generation_resolution=generation_resolution,
        delivery_fps=project.delivery_fps,
        delivery_resolution=project.delivery_resolution,
    )


def build_render_plan(
    project_id: str,
    scene_id: str,
    shot_id: str,
    *,
    engine_name: str | None = None,
    require_assets: bool = True,
) -> RenderPlan:
    from app.video.engine import get_engine, select_engine

    project = get_project(project_id)
    scene = find_scene(project, scene_id)
    shot = find_shot(scene, shot_id)
    engine = get_engine(engine_name) if engine_name else select_engine(shot.engine_profile)
    return build_render_plan_from_objects(
        project,
        scene,
        shot,
        engine.capabilities(),
        require_assets=require_assets,
    )
