from __future__ import annotations

import json

from app.video.cinematic_models import ProjectUpdateRequest, RenderPlan
from app.video.cinematic_requests import ShotRenderRequest
from app.video.models import VideoGenerationRequest


_CONTINUITY_PRIORITY = (
    'characters',
    'wardrobe',
    'props',
    'location',
    'weather',
    'lighting',
    'time_of_day',
    'geography',
    'camera_language',
    'color_language',
    'physical_state',
    'story_state',
    'immutable_constraints',
    'freeform_notes',
)


def _truncate_text(value: str, limit: int) -> str:
    value = ' '.join(value.split())
    if len(value) <= limit:
        return value
    if limit <= 0:
        return ''
    cut = value.rfind(' ', 0, limit + 1)
    if cut < max(1, limit // 2):
        cut = limit
    return value[:cut].rstrip()


def _compact_value(value) -> str:
    if isinstance(value, str):
        return ' '.join(value.split())
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _continuity_summary(plan: RenderPlan) -> str:
    data = plan.effective_continuity.model_dump(mode='python', exclude_none=True)
    pieces: list[str] = []
    for field in _CONTINUITY_PRIORITY:
        value = data.get(field)
        if value in (None, '', {}, []):
            continue
        pieces.append(f"{field.replace('_', ' ')}: {_compact_value(value)}")
    return '; '.join(pieces)


def pack_engine_prompt(plan: RenderPlan, *, max_chars: int = 2000) -> str:
    """Pack shot-local intent + continuity into a deterministic engine prompt.

    The project master prompt is intentionally unavailable to this function, so it
    cannot accidentally leak into individual engine requests. The shot action owns
    most of the budget; negative/continuity constraints receive a bounded suffix.
    """
    if max_chars < 128:
        raise ValueError('max_chars must be at least 128')

    suffix_parts: list[str] = []
    if plan.negative_prompt.strip():
        suffix_parts.append(f'Avoid: {plan.negative_prompt.strip()}')
    continuity = _continuity_summary(plan)
    if continuity:
        suffix_parts.append(f'Continuity: {continuity}')

    suffix = '\n\n'.join(suffix_parts)
    if not suffix:
        return _truncate_text(plan.prompt, max_chars)

    suffix_budget = min(700, max(220, max_chars // 3))
    packed_suffix = _truncate_text(suffix, suffix_budget)
    separator = '\n\n'
    action_budget = max_chars - len(separator) - len(packed_suffix)
    action = _truncate_text(plan.prompt, action_budget)
    packed = f'{action}{separator}{packed_suffix}'.strip()
    if not packed:
        raise ValueError('Engine prompt became empty after packing')
    return packed[:max_chars]


def render_shot(
    project_id: str,
    scene_id: str,
    shot_id: str,
    request: ShotRenderRequest,
) -> dict:
    from app.video import cinematic_service as service
    from app.video.engine import get_engine, select_engine, validate_request_for_engine
    from app.video.jobs import enqueue_video_job

    project = service.get_project(project_id)
    if project.revision != request.expected_revision:
        raise service.ProjectRevisionConflict(project_id, request.expected_revision, project.revision)

    scene = service.find_scene(project, scene_id)
    shot = service.find_shot(scene, shot_id)
    references = service.resolve_reference_ids(project, scene, shot, require_assets=True)
    if not references:
        raise FileNotFoundError('Cinematic shot render requires at least one reference image')

    engine = get_engine(request.engine_name) if request.engine_name else select_engine(shot.engine_profile)
    capabilities = engine.capabilities()
    plan = service.build_render_plan_from_objects(
        project,
        scene,
        shot,
        capabilities,
        require_assets=False,
    )
    if plan.source_image_id is None:
        raise FileNotFoundError('Cinematic shot render requires a source image')

    engine_prompt = pack_engine_prompt(plan, max_chars=2000)
    generation_request = VideoGenerationRequest(
        image_id=plan.source_image_id,
        prompt=engine_prompt,
        engine_profile=plan.engine_profile,
        seed=plan.seed,
        duration_seconds=plan.duration_seconds,
        fps=plan.generation_fps,
        resolution=plan.generation_resolution,
        motion_strength=plan.motion_strength,
        camera_motion=plan.camera_motion,
    )
    validate_request_for_engine(generation_request, capabilities)

    linked: dict[str, object] = {}

    def link_job(job_id: str, _job: dict) -> None:
        fresh = service.get_project(project_id)
        if fresh.revision != request.expected_revision:
            raise service.ProjectRevisionConflict(project_id, request.expected_revision, fresh.revision)
        fresh_scene = service.find_scene(fresh, scene_id)
        fresh_shot = service.find_shot(fresh_scene, shot_id)
        updated_shot = fresh_shot.model_copy(
            update={
                'latest_job_id': job_id,
                'latest_rendered_project_revision': request.expected_revision,
            }
        )
        updated_shots = [
            updated_shot if candidate.shot_id == shot_id else candidate
            for candidate in fresh_scene.shots
        ]
        updated_scene = fresh_scene.model_copy(update={'shots': updated_shots})
        updated_scenes = [
            updated_scene if candidate.scene_id == scene_id else candidate
            for candidate in fresh.scenes
        ]
        linked['project'] = service.update_project(
            project_id,
            ProjectUpdateRequest(
                expected_revision=request.expected_revision,
                scenes=updated_scenes,
            ),
        )

    metadata = {
        'project_id': project_id,
        'scene_id': scene_id,
        'shot_id': shot_id,
        'project_revision': request.expected_revision,
    }
    job = enqueue_video_job(
        generation_request,
        engine_name=plan.engine_name,
        metadata=metadata,
        before_submit=link_job,
    )
    return {
        'job': job,
        'project': linked['project'],
        'plan': plan,
    }
