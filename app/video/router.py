from __future__ import annotations

import io
import os
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError

from app.video.models import PrivacyPreferences, VideoGenerationRequest
from app.video.runtime import detect_video_runtime
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
    return {
        'backend': True,
        'runtime': detect_video_runtime().model_dump(mode='json'),
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
    raise HTTPException(503, 'Local video generation worker is not ready yet')
