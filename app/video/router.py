from __future__ import annotations

import io
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import ValidationError

from app.video.models import PrivacyPreferences, VideoGenerationRequest
from app.video.runtime import detect_video_runtime
from app.video.storage import (
    get_video_record,
    list_video_records,
    put_video_record,
    video_asset_path,
)


router = APIRouter(prefix='/api/video', tags=['Private video studio'])
_MAX_IMAGE_BYTES = 12 * 1024 * 1024
_MAX_IMAGE_PIXELS = 20_000_000
_PRIVACY_ID = '0' * 32


@router.get('/capabilities')
def capabilities():
    return detect_video_runtime().model_dump(mode='json')


@router.post('/images')
async def upload_image(file: UploadFile = File(...)):
    raw = await file.read(_MAX_IMAGE_BYTES + 1)
    await file.close()
    if len(raw) > _MAX_IMAGE_BYTES:
        raise HTTPException(413, 'Image exceeds 12 MiB')
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in {'PNG', 'JPEG', 'WEBP'} or image.width * image.height > _MAX_IMAGE_PIXELS:
                raise ValueError('Use PNG/JPEG/WebP up to 20 megapixels')
            normalized = ImageOps.exif_transpose(image).convert('RGB')
            identifier = uuid.uuid4().hex
            normalized.save(video_asset_path(identifier, 'png'), format='PNG')
    except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, 'Invalid or unsupported image') from exc
    put_video_record('video_asset_meta', {'type': 'source_image', 'format': 'png'}, identifier)
    return {'image_id': identifier, 'url': f'/api/video/assets/{identifier}.png'}


@router.get('/jobs')
def jobs():
    return list_video_records('video_job')


@router.get('/jobs/{identifier}')
def job(identifier: str):
    try:
        return get_video_record('video_job', identifier)
    except KeyError as exc:
        raise HTTPException(404, 'Video job not found') from exc


@router.get('/assets/{filename}')
def asset(filename: str):
    try:
        identifier, extension = filename.rsplit('.', 1)
        if extension not in {'png', 'mp4'}:
            raise ValueError('Unsupported public asset extension')
        path = video_asset_path(identifier, extension)
    except ValueError as exc:
        raise HTTPException(404, 'Video asset not found') from exc
    if not path.is_file():
        raise HTTPException(404, 'Video asset not found')
    media_type = 'video/mp4' if extension == 'mp4' else 'image/png'
    return FileResponse(path, media_type=media_type, filename=filename)


def _privacy_preferences() -> PrivacyPreferences:
    try:
        record = get_video_record('video_privacy', _PRIVACY_ID)
        record.pop('id', None)
        return PrivacyPreferences.model_validate(record)
    except KeyError:
        return PrivacyPreferences()


@router.get('/privacy')
def get_privacy():
    return _privacy_preferences().model_dump(mode='json')


@router.put('/privacy')
def put_privacy(payload: dict):
    current = _privacy_preferences().model_dump()
    try:
        updated = PrivacyPreferences.model_validate({**current, **payload})
    except ValidationError as exc:
        raise HTTPException(422, detail=exc.errors()) from exc
    saved = put_video_record('video_privacy', updated.model_dump(), _PRIVACY_ID)
    saved.pop('id', None)
    return saved


@router.post('/generate')
def generate(req: VideoGenerationRequest):
    try:
        from app.video.jobs import enqueue_video_job
    except ImportError as exc:
        raise HTTPException(503, 'Local video generation worker is not installed yet') from exc
    return enqueue_video_job(req)
