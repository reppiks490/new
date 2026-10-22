from __future__ import annotations

import os
from pathlib import Path
import time
import uuid

from PIL import Image

from app.gpu_worker import gpu_pool
from app.image.engine import ImageEngineUnavailableError, get_engine, select_engine
from app.image.models import ImageEditRequest
from app.image.storage import get_image_record, image_asset_path, list_image_records, put_image_record
from app.studio.storage import root as studio_root


pool = gpu_pool


def _update_job(identifier: str, **changes) -> dict:
    value = get_image_record('image_job', identifier)
    value.pop('id', None)
    return put_image_record('image_job', {**value, **changes}, identifier=identifier)


def _sanitize_error(exc: Exception) -> str:
    message = str(exc) or exc.__class__.__name__
    for name, value in os.environ.items():
        if not value or len(value.strip()) < 4:
            continue
        upper = name.upper()
        if any(marker in upper for marker in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD')):
            message = message.replace(value, '[redacted]').replace(value.strip(), '[redacted]')
    try:
        workspace = str(studio_root())
        if workspace:
            message = message.replace(workspace, '[workspace]')
    except Exception:
        pass
    return message[:1000]


def _valid_png(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < 8:
        return False
    try:
        with Image.open(path) as image:
            return image.format == 'PNG'
    except OSError:
        return False


def _job_record(request: ImageEditRequest, engine_name: str) -> dict:
    return {
        'created': time.time(),
        'status': 'queued',
        'stage': 'Queued',
        'progress': 0,
        'engine': engine_name,
        'image_id': request.image_id,
        'seed': request.seed,
        'prompt_chars': len(request.prompt),
    }


def enqueue_image_job(request: ImageEditRequest) -> dict:
    engine = select_engine()
    source_path = image_asset_path(request.image_id, 'png')
    if not source_path.is_file():
        raise FileNotFoundError('Uploaded source image was not found')

    identifier = uuid.uuid4().hex
    job = put_image_record('image_job', _job_record(request, engine.name), identifier=identifier)
    try:
        pool.submit(execute_image_job, identifier, request, engine.name)
    except RuntimeError as exc:
        _update_job(
            identifier,
            status='failed',
            stage='Stopped',
            error='Local image worker is unavailable. Please retry.',
        )
        raise ImageEngineUnavailableError('Local image worker is unavailable. Please retry.') from exc
    return job


def execute_image_job(identifier: str, request: ImageEditRequest, engine_name: str) -> None:
    output_path: Path | None = None
    try:
        _update_job(identifier, status='running', stage='Loading', progress=5)
        engine = get_engine(engine_name)
        if not engine.capabilities().available:
            raise ImageEngineUnavailableError(engine.capabilities().detail)
        source_path = image_asset_path(request.image_id, 'png')
        if not source_path.is_file():
            raise FileNotFoundError('Uploaded source image was not found')

        asset_id = uuid.uuid4().hex
        output_path = image_asset_path(asset_id, 'png')
        _update_job(identifier, stage='Generating', progress=10)

        def report(stage: str, progress: int) -> None:
            stage_name = 'Encoding' if stage.lower() == 'encoding' else 'Generating'
            value = max(10, min(94, int(progress)))
            _update_job(identifier, stage=stage_name, progress=value)

        produced = engine.generate(
            request=request,
            source_path=source_path,
            output_path=output_path,
            progress=report,
        )
        if produced != output_path:
            raise RuntimeError('Image engine returned an unexpected output path')
        _update_job(identifier, stage='Encoding', progress=95)
        if not _valid_png(output_path):
            raise RuntimeError('Image engine did not produce a valid PNG')
        _update_job(
            identifier,
            status='succeeded',
            stage='Ready',
            progress=100,
            asset_id=asset_id,
            asset_url=f'/api/image/assets/{asset_id}.png',
        )
    except Exception as exc:
        if output_path is not None and output_path.exists():
            try:
                output_path.unlink()
            except OSError:
                pass
        _update_job(
            identifier,
            status='failed',
            stage='Stopped',
            error=_sanitize_error(exc),
        )


def interrupt_active_image_jobs() -> int:
    interrupted = 0
    for job in list_image_records('image_job'):
        if job.get('status') not in {'queued', 'running'}:
            continue
        _update_job(
            job['id'],
            status='failed',
            stage='Interrupted',
            error='Worker restarted; local image generation was not automatically resubmitted.',
        )
        interrupted += 1
    return interrupted
