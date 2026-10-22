from __future__ import annotations

import io
import os
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError

from app.image.engine import ImageEngineUnavailableError, registered_image_engine_capabilities
from app.image.jobs import enqueue_image_job
from app.image.models import ImageEditRequest
from app.image.storage import get_image_record, image_asset_path, list_image_records


router = APIRouter(prefix='/api/image', tags=['Local image studio'])
_MAX_IMAGE_BYTES = 12 * 1024 * 1024
_MAX_IMAGE_PIXELS = 20_000_000


@router.get('/capabilities')
def capabilities():
    return {
        'backend': True,
        'engines': [item.model_dump(mode='json') for item in registered_image_engine_capabilities()],
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
            normalized.save(image_asset_path(identifier, 'png'), format='PNG')
    except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, 'Invalid or unsupported image') from exc
    return {'image_id': identifier, 'url': f'/api/image/assets/{identifier}.png'}


@router.get('/assets/{filename}')
def asset(filename: str):
    try:
        identifier, extension = filename.rsplit('.', 1)
        if extension != 'png':
            raise ValueError('Unsupported public asset type')
        path = image_asset_path(identifier, extension)
    except ValueError:
        raise HTTPException(404, 'Asset not found')
    if not path.is_file():
        raise HTTPException(404, 'Asset not found')
    return FileResponse(path, media_type='image/png', headers={'Cache-Control': 'no-store'})


@router.get('/jobs')
def jobs():
    return list_image_records('image_job')


@router.get('/jobs/{identifier}')
def job(identifier: str):
    try:
        return get_image_record('image_job', identifier)
    except KeyError:
        raise HTTPException(404, 'Image job not found')


@router.post('/generate')
def generate(req: ImageEditRequest):
    try:
        source_path = image_asset_path(req.image_id, 'png')
    except ValueError as exc:
        raise HTTPException(422, 'Invalid source image identifier') from exc
    if not source_path.is_file():
        raise HTTPException(422, 'Uploaded source image was not found')
    try:
        return enqueue_image_job(req)
    except ImageEngineUnavailableError as exc:
        raise HTTPException(503, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(422, str(exc)) from exc
