from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
import time
import uuid

from app.studio import storage as studio_storage
from app.video.engine import ImageToVideoEngine, select_engine, validate_engine_request
from app.video.models import VideoGenerationRequest
from app.video.storage import get_video_record, put_video_record, video_asset_path


pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='video')


class VideoEngineUnavailable(RuntimeError):
    pass


class VideoSourceMissing(ValueError):
    pass


def _sanitize_error(exc: Exception) -> str:
    message = str(exc)
    for key, value in os.environ.items():
        if ('TOKEN' in key.upper() or 'KEY' in key.upper()) and value and len(value.strip()) >= 4:
            message = message.replace(value, '[redacted]').replace(value.strip(), '[redacted]')
    return message[:1000]


def _update_job(identifier: str, **changes) -> dict:
    current = get_video_record('video_job', identifier)
    current.pop('id', None)
    history = list(current.get('history') or [])
    stage = changes.get('stage')
    if stage and (not history or history[-1] != stage):
        history.append(stage)
    value = {**current, **changes, 'history': history, 'updated': time.time()}
    return put_video_record('video_job', value, identifier)


def enqueue_video_job(req: VideoGenerationRequest) -> dict:
    source = video_asset_path(req.image_id, 'png')
    if not source.is_file():
        raise VideoSourceMissing('Source image does not exist')
    selected = select_engine(req.engine_profile)
    if selected is None:
        raise VideoEngineUnavailable('No compatible local image-to-video engine is available; no paid fallback is configured.')
    validate_engine_request(req, selected.capabilities())

    identifier = uuid.uuid4().hex
    caps = selected.capabilities()
    record = put_video_record('video_job', {
        'status': 'queued',
        'stage': 'Queued',
        'history': ['Queued'],
        'progress': 0,
        'created': time.time(),
        'engine': caps.name,
        'engine_profile': req.engine_profile,
        'image_id': req.image_id,
        'seed': req.seed,
        'duration_seconds': req.duration_seconds,
        'fps': req.fps,
        'resolution': req.resolution,
    }, identifier)
    try:
        pool.submit(execute_video_job, identifier, req, selected)
    except RuntimeError as exc:
        _update_job(identifier, status='failed', stage='Stopped', error='Video worker is unavailable. Please retry.')
        raise VideoEngineUnavailable('Video worker is unavailable. Please retry.') from exc
    return record


def execute_video_job(identifier: str, req: VideoGenerationRequest, selected: ImageToVideoEngine | None = None) -> None:
    try:
        engine = selected or select_engine(req.engine_profile)
        if engine is None:
            raise VideoEngineUnavailable('No compatible local image-to-video engine is available; no paid fallback is configured.')
        validate_engine_request(req, engine.capabilities())
        source = video_asset_path(req.image_id, 'png')
        if not source.is_file():
            raise VideoSourceMissing('Source image does not exist')

        _update_job(identifier, status='running', stage='Loading', progress=5)
        output_id = uuid.uuid4().hex
        output_path = video_asset_path(output_id, 'mp4')

        def progress(stage: str, percent: int) -> None:
            stage_name = {'generating': 'Generating', 'encoding': 'Encoding'}.get(stage, stage.title())
            _update_job(identifier, status='running', stage=stage_name, progress=max(0, min(99, int(percent))))

        produced = engine.generate(req, source, output_path, progress)
        if produced != output_path or not output_path.is_file():
            raise RuntimeError('Local engine did not produce the expected MP4 output')
        header = output_path.read_bytes()[:64]
        if output_path.stat().st_size < 32 or b'ftyp' not in header:
            raise RuntimeError('Local engine produced an invalid MP4 container')

        put_video_record('video_asset_meta', {
            'type': 'generated_video',
            'format': 'mp4',
            'engine': engine.capabilities().name,
            'job_id': identifier,
        }, output_id)
        _update_job(
            identifier,
            status='succeeded',
            stage='Ready',
            progress=100,
            asset_id=output_id,
            asset_url=f'/api/video/assets/{output_id}.mp4',
        )
    except Exception as exc:
        _update_job(identifier, status='failed', stage='Stopped', error=_sanitize_error(exc))


def interrupt_active_video_jobs() -> int:
    with studio_storage.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        rows = db.execute(
            "SELECT id,data FROM records WHERE kind='video_job' "
            "AND json_extract(data, '$.status') IN ('queued','running')"
        ).fetchall()
        for identifier, raw in rows:
            value = json.loads(raw)
            history = list(value.get('history') or [])
            if not history or history[-1] != 'Interrupted':
                history.append('Interrupted')
            value.update({
                'status': 'failed',
                'stage': 'Interrupted',
                'history': history,
                'error': 'Local video worker restarted. Interrupted jobs are never auto-resubmitted.',
                'updated': time.time(),
            })
            db.execute(
                'UPDATE records SET data=?, updated=? WHERE id=?',
                (json.dumps(value, allow_nan=False), time.time(), identifier),
            )
    return len(rows)
