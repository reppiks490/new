from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import time
import uuid

from app.video.engine import (
    EngineUnavailableError,
    get_engine,
    select_engine,
    validate_request_for_engine,
)
from app.video.models import VideoGenerationRequest
from app.video.storage import get_video_record, list_video_records, put_video_record, video_asset_path
from app.studio.storage import root as studio_root


pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='video-gpu')


def _update_job(identifier: str, **changes) -> dict:
    value = get_video_record('video_job', identifier)
    value.pop('id', None)
    return put_video_record('video_job', {**value, **changes}, identifier=identifier)


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


def _valid_mp4(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < 12:
        return False
    with path.open('rb') as handle:
        return b'ftyp' in handle.read(64)


def _job_record(request: VideoGenerationRequest, engine_name: str) -> dict:
    return {
        'created': time.time(),
        'status': 'queued',
        'stage': 'Queued',
        'progress': 0,
        'engine': engine_name,
        'engine_profile': request.engine_profile,
        'image_id': request.image_id,
        'seed': request.seed,
        'duration_seconds': request.duration_seconds,
        'fps': request.fps,
        'resolution': request.resolution,
        'motion_strength': request.motion_strength,
        'camera_motion': request.camera_motion,
        'prompt_chars': len(request.prompt),
    }


def enqueue_video_job(request: VideoGenerationRequest) -> dict:
    engine = select_engine(request.engine_profile)
    validate_request_for_engine(request, engine.capabilities())
    source_path = video_asset_path(request.image_id, 'png')
    if not source_path.is_file():
        raise FileNotFoundError('Uploaded source image was not found')

    identifier = uuid.uuid4().hex
    job = put_video_record('video_job', _job_record(request, engine.name), identifier=identifier)
    try:
        pool.submit(execute_video_job, identifier, request, engine.name)
    except RuntimeError as exc:
        _update_job(
            identifier,
            status='failed',
            stage='Stopped',
            error='Local video worker is unavailable. Please retry.',
        )
        raise EngineUnavailableError('Local video worker is unavailable. Please retry.') from exc
    return job


def execute_video_job(identifier: str, request: VideoGenerationRequest, engine_name: str) -> None:
    output_path: Path | None = None
    try:
        _update_job(identifier, status='running', stage='Loading', progress=5)
        engine = get_engine(engine_name)
        capabilities = engine.capabilities()
        validate_request_for_engine(request, capabilities)
        source_path = video_asset_path(request.image_id, 'png')
        if not source_path.is_file():
            raise FileNotFoundError('Uploaded source image was not found')

        asset_id = uuid.uuid4().hex
        output_path = video_asset_path(asset_id, 'mp4')
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
            raise RuntimeError('Video engine returned an unexpected output path')
        _update_job(identifier, stage='Encoding', progress=95)
        if not _valid_mp4(output_path):
            raise RuntimeError('Video engine did not produce a valid MP4 container')
        _update_job(
            identifier,
            status='succeeded',
            stage='Ready',
            progress=100,
            asset_id=asset_id,
            asset_url=f'/api/video/assets/{asset_id}.mp4',
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


def interrupt_active_video_jobs() -> int:
    interrupted = 0
    for job in list_video_records('video_job'):
        if job.get('status') not in {'queued', 'running'}:
            continue
        _update_job(
            job['id'],
            status='failed',
            stage='Interrupted',
            error='Worker restarted; local video generation was not automatically resubmitted.',
        )
        interrupted += 1
    return interrupted
