from __future__ import annotations

import io
import os
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError

from app.video.cinematic_models import ProjectCreateRequest, ProjectUpdateRequest
from app.video.cinematic_requests import CompileProjectRequest
from app.video.cinematic_service import (
    ProjectRevisionConflict,
    build_render_plan,
    compile_project,
    create_project,
    get_project,
    list_projects,
    update_project,
)
from app.video.models import PrivacyPreferences, VideoGenerationRequest
from app.video.runtime import detect_video_runtime
from app.video.engine import EngineUnavailableError, UnsupportedEngineControl, registered_engine_capabilities
from app.video.jobs import enqueue_video_job
from app.video.storage import (
    get_video_record,
    list_video_records,
    put_video_record,
    video_asset_path,
)

router = APIRouter(prefix='/api/video', tags=['Local video studio'])
_MAX_IMAGE_BYTES = 12 * 1024 * 1024
_MAX_IMAGE_PIXELS = 20_000_000
_PRIVACY_ID = '0' * 32


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {'0', 'false', 'no', 'off'}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _default_privacy() -> PrivacyPreferences:
    return PrivacyPreferences(
        privacy_mode=_env_bool('CHARACTER3D_VIDEO_PRIVACY_DEFAULT', True),
        quick_hide=_env_bool('CHARACTER3D_VIDEO_QUICK_HIDE_ENABLED', True),
        idle_lock_seconds=_env_int('CHARACTER3D_VIDEO_IDLE_LOCK_SECONDS', 30),
        require_unlock_on_resume=_env_bool('CHARACTER3D_VIDEO_REQUIRE_UNLOCK_ON_RESUME', True),
    )


@router.get('/capabilities')
def capabilities():
    runtime = detect_video_runtime()
    runtime.engines = registered_engine_capabilities()
    return {
        'backend': True,
        'runtime': runtime.model_dump(mode='json'),
        'auth_required': bool(os.getenv('CHARACTER3D_STUDIO_TOKEN')),
    }


@router.post('/images')
async def upload_image(file: UploadFile = File(...)):
    raw = await file.read(_MAX_IMAGE_BYTES + 1)
    await file.close()
    if len(raw) > _MAX_IMAGE_BYTES:
        raise HTTPException(413, 'Image exceeds 12 MiB')
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.format not in {'PNG', 'JPEG', 'WEBP'} or source.width * source.height > _MAX_IMAGE_PIXELS:
                raise ValueError('Use PNG/JPEG/WebP up to 20 megapixels')
            normalized = ImageOps.exif_transpose(source).convert('RGB')
            identifier = uuid.uuid4().hex
            normalized.save(video_asset_path(identifier, 'png'), format='PNG')
    except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, 'Invalid or unsupported image') from exc
    return {'image_id': identifier, 'url': f'/api/video/assets/{identifier}.png'}


@router.get('/assets/{filename}')
def asset(filename: str):
    try:
        identifier, extension = filename.rsplit('.', 1)
        if extension not in {'png', 'mp4'}:
            raise ValueError('Unsupported public asset type')
        path = video_asset_path(identifier, extension)
    except ValueError:
        raise HTTPException(404, 'Asset not found')
    if not path.is_file():
        raise HTTPException(404, 'Asset not found')
    return FileResponse(
        path,
        media_type='video/mp4' if extension == 'mp4' else 'image/png',
        headers={'Cache-Control': 'no-store'},
    )


@router.get('/privacy', response_model=PrivacyPreferences)
def privacy():
    try:
        record = get_video_record('video_privacy', _PRIVACY_ID)
    except KeyError:
        return _default_privacy()
    record.pop('id', None)
    return PrivacyPreferences.model_validate(record)


@router.put('/privacy', response_model=PrivacyPreferences)
def set_privacy(preferences: PrivacyPreferences):
    put_video_record('video_privacy', preferences.model_dump(mode='json'), identifier=_PRIVACY_ID)
    return preferences


@router.get('/projects')
def cinematic_projects():
    return list_projects()


@router.post('/projects')
def create_cinematic_project(request: ProjectCreateRequest):
    return create_project(request)


@router.get('/projects/{project_id}')
def cinematic_project(project_id: str):
    try:
        return get_project(project_id)
    except (KeyError, ValueError):
        raise HTTPException(404, 'Cinematic project not found')


@router.put('/projects/{project_id}')
def replace_cinematic_project(project_id: str, request: ProjectUpdateRequest):
    try:
        return update_project(project_id, request)
    except ProjectRevisionConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, 'Cinematic project not found') from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post('/projects/{project_id}/compile')
def compile_cinematic_project(project_id: str, request: CompileProjectRequest):
    try:
        project, diagnostics = compile_project(project_id, request)
        return {'project': project, 'diagnostics': diagnostics}
    except ProjectRevisionConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, 'Cinematic project or engine not found') from exc
    except EngineUnavailableError as exc:
        raise HTTPException(503, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get('/projects/{project_id}/scenes/{scene_id}/shots/{shot_id}/plan')
def cinematic_shot_plan(
    project_id: str,
    scene_id: str,
    shot_id: str,
    engine_name: str | None = None,
):
    try:
        return build_render_plan(
            project_id,
            scene_id,
            shot_id,
            engine_name=engine_name,
            require_assets=True,
        )
    except KeyError as exc:
        raise HTTPException(404, 'Cinematic project, scene, or shot not found') from exc
    except FileNotFoundError as exc:
        raise HTTPException(422, str(exc)) from exc
    except EngineUnavailableError as exc:
        raise HTTPException(503, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get('/jobs')
def jobs():
    return list_video_records('video_job')


@router.get('/jobs/{identifier}')
def job(identifier: str):
    try:
        return get_video_record('video_job', identifier)
    except KeyError:
        raise HTTPException(404, 'Video job not found')


@router.post('/generate')
def generate(req: VideoGenerationRequest):
    try:
        source_path = video_asset_path(req.image_id, 'png')
    except ValueError as exc:
        raise HTTPException(422, 'Invalid source image identifier') from exc
    if not source_path.is_file():
        raise HTTPException(422, 'Uploaded source image was not found')
    try:
        return enqueue_video_job(req)
    except UnsupportedEngineControl as exc:
        raise HTTPException(422, str(exc)) from exc
    except EngineUnavailableError as exc:
        raise HTTPException(503, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(422, str(exc)) from exc
