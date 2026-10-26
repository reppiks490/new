from __future__ import annotations

import hashlib
import io
import os
import uuid

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from PIL import Image, ImageOps, UnidentifiedImageError

from app.video.cinematic_models import ProjectCreateRequest, ProjectUpdateRequest
from app.video.cinematic_assembly_jobs import (
    AssemblyCancellationConflict, AssemblyQueueFull,
    cancel_queued_master_assembly, enqueue_master_assembly,
    get_master_assembly_job, list_master_assembly_jobs,
)
from app.video.cinematic_requests import (
    AssembleMasterRequest, BatchRenderRequest, CompileProjectRequest, ShotRenderRequest,
)
from app.video.cinematic_service import (
    MasterAssemblyNotReady,
    FilmDurationExceeded,
    ProjectRevisionConflict,
    assemble_project_master,
    build_render_plan,
    compile_project,
    create_project,
    get_project,
    list_projects,
    project_render_status,
    render_project_missing,
    render_shot,
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


def _open_private_asset(path):
    """Pin a regular asset inode before the HTTP response can stream bytes.

    POSIX no-follow directory-relative opens close the check-then-FileResponse
    symlink race. Windows requires separate reparse-point/ACL verification.
    """
    import stat

    flags = os.O_RDONLY | getattr(os, 'O_CLOEXEC', 0) | getattr(os, 'O_NONBLOCK', 0)
    if os.name == 'posix':
        if not hasattr(os, 'O_NOFOLLOW') or not hasattr(os, 'O_DIRECTORY'):
            raise OSError('Safe asset open is unsupported')
        directory_fd = os.open(
            path.parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            | getattr(os, 'O_CLOEXEC', 0),
        )
        try:
            fd = os.open(path.name, flags | os.O_NOFOLLOW, dir_fd=directory_fd)
        finally:
            os.close(directory_fd)
    else:
        fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        current = os.lstat(path)
        if (not stat.S_ISREG(opened.st_mode)
                or not stat.S_ISREG(current.st_mode)
                or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)):
            raise OSError('Asset path changed or is not a regular file')
        return fd, opened
    except BaseException:
        os.close(fd)
        raise



def _snapshot_private_asset(fd, opened, directory, ranges=None):
    """Create an unlinked, owner-private byte snapshot before HTTP headers.

    A pinned source descriptor prevents path swaps but not same-inode writes.
    Read in bounded chunks, and reject concurrent rewrites using the original
    descriptor's high-resolution identity/change metadata. TemporaryFile is
    unlinked (or opened with O_TMPFILE) on POSIX; its duplicate descriptor
    survives the context manager until the ASGI response closes it.

    This intentionally trades one temporary on-disk copy per GET for stable
    bytes. Large-film disk/throughput limits require lead review before merge.
    """
    import tempfile

    def identity(stat_result):
        return (
            stat_result.st_dev, stat_result.st_ino, stat_result.st_size,
            stat_result.st_mtime_ns, stat_result.st_ctime_ns,
        )

    expected = identity(opened)
    if identity(os.fstat(fd)) != expected:
        raise ValueError('Asset changed before private snapshot')
    with tempfile.TemporaryFile(mode='w+b', dir=directory) as temporary:
        # Only snapshot requested byte spans for mobile Range GETs. A tiny
        # metadata/sample request must not duplicate a multi-GB film on disk.
        # Holes in the unlinked temporary file are never returned to clients.
        spans = ranges if ranges is not None else [(0, opened.st_size - 1)]
        for start, end in spans:
            offset = start
            while offset <= end:
                count = min(256 * 1024, end - offset + 1)
                if hasattr(os, 'pread'):
                    chunk = os.pread(fd, count, offset)
                else:
                    os.lseek(fd, offset, os.SEEK_SET)
                    chunk = os.read(fd, count)
                if not chunk:
                    raise ValueError('Asset truncated during private snapshot')
                temporary.seek(offset)
                temporary.write(chunk)
                offset += len(chunk)
        if identity(os.fstat(fd)) != expected:
            raise ValueError('Asset changed during private snapshot')
        temporary.flush()
        return os.dup(temporary.fileno())


def _asset_byte_ranges(header: str, size: int) -> list[tuple[int, int]]:
    """Parse bounded RFC 7233 byte ranges; reject malformed/unsatisfiable input."""
    import re

    if not header.startswith('bytes='):
        raise ValueError('Unsupported range unit')
    components = header[6:].split(',')
    if not 1 <= len(components) <= 16:
        raise ValueError('Invalid range count')
    ranges = []
    for component in components:
        match = re.fullmatch(r'(\d*)-(\d*)', component.strip())
        if not match or (not match.group(1) and not match.group(2)):
            raise ValueError('Invalid byte range')
        if not match.group(1):
            suffix = int(match.group(2))
            if suffix <= 0 or size <= 0:
                raise ValueError('Unsatisfiable suffix range')
            start, end = max(0, size - suffix), size - 1
        else:
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else size - 1
            if start >= size or end < start:
                raise ValueError('Unsatisfiable byte range')
            end = min(end, size - 1)
        ranges.append((start, end))

    # RFC 7233 permits coalescing overlapping/adjacent ranges. Without it,
    # one authenticated request can retransmit a large private master up to
    # sixteen times using duplicate full-file spans. Preserve the order of
    # the first requested member of each merged group for mobile clients.
    ordered = sorted(enumerate(ranges), key=lambda item: item[1][0])
    merged = []
    for original_index, (start, end) in ordered:
        if merged and start <= merged[-1][2] + 1:
            first_index, first_start, first_end = merged[-1]
            merged[-1] = (
                min(first_index, original_index), first_start, max(first_end, end),
            )
        else:
            merged.append((original_index, start, end))
    return [(start, end) for _, start, end in sorted(merged)]


class _OpenedAssetResponse(Response):
    """ASGI response reads exclusively from an opened inode, never its path."""

    def __init__(self, fd, size, ranges, media_type, headers, status_code):
        self._fd = fd
        self._ranges = ranges
        self._size = size
        self._media_type = media_type
        self._boundary = uuid.uuid4().hex if ranges and len(ranges) > 1 else None
        if self._boundary:
            headers['Content-Type'] = f'multipart/byteranges; boundary={self._boundary}'
            headers['Content-Length'] = str(
                sum(
                    len(self._part_header(start, end)) + end - start + 1 + 2
                    for start, end in ranges
                ) + len(self._closing_boundary())
            )
        elif ranges:
            start, end = ranges[0]
            headers['Content-Range'] = f'bytes {start}-{end}/{size}'
            headers['Content-Length'] = str(end - start + 1)
        else:
            headers['Content-Length'] = str(size)
        super().__init__(
            content=b'', status_code=status_code,
            media_type=media_type, headers=headers,
        )

    def _part_header(self, start, end):
        return (
            f'--{self._boundary}\r\nContent-Type: {self._media_type}\r\n'
            f'Content-Range: bytes {start}-{end}/{self._size}\r\n\r\n'
        ).encode('ascii')

    def _closing_boundary(self):
        return f'--{self._boundary}--\r\n'.encode('ascii')

    async def __call__(self, scope, receive, send):
        import anyio

        def read_at(offset, count):
            if hasattr(os, 'pread'):
                return os.pread(self._fd, count, offset)
            os.lseek(self._fd, offset, os.SEEK_SET)
            return os.read(self._fd, count)

        try:
            await send({
                'type': 'http.response.start',
                'status': self.status_code,
                'headers': self.raw_headers,
            })
            if scope.get('method') != 'HEAD':
                spans = self._ranges if self._ranges is not None else [(0, self._size - 1)]
                for start, end in spans:
                    if self._boundary:
                        await send({
                            'type': 'http.response.body',
                            'body': self._part_header(start, end),
                            'more_body': True,
                        })
                    offset = start
                    while offset <= end:
                        data = await anyio.to_thread.run_sync(
                            read_at, offset, min(256 * 1024, end - offset + 1),
                        )
                        if not data:
                            raise OSError('Asset changed during descriptor-backed streaming')
                        await send({
                            'type': 'http.response.body',
                            'body': data,
                            'more_body': True,
                        })
                        offset += len(data)
                    if self._boundary:
                        await send({
                            'type': 'http.response.body', 'body': b'\r\n',
                            'more_body': True,
                        })
                if self._boundary:
                    await send({
                        'type': 'http.response.body',
                        'body': self._closing_boundary(), 'more_body': True,
                    })
            await send({'type': 'http.response.body', 'body': b'', 'more_body': False})
        finally:
            os.close(self._fd)


@router.head('/assets/{filename}')
@router.get('/assets/{filename}')
def asset(filename: str, request: Request):
    try:
        identifier, extension = filename.rsplit('.', 1)
        if extension not in {'png', 'mp4'}:
            raise ValueError('Unsupported public asset type')
        path = video_asset_path(identifier, extension)
        fd, opened = _open_private_asset(path)
    except (ValueError, OSError):
        raise HTTPException(404, 'Asset not found')
    try:
        from email.utils import formatdate

        media_type = 'video/mp4' if extension == 'mp4' else 'image/png'
        # A same-length atomic master replacement can preserve mtime while
        # changing the file identity. Include the opened inode and change
        # time in an opaque validator, not just the public mtime/size pair.
        # This is not a cryptographic content attestation: an in-place
        # concurrent rewrite still needs immutable media publication.
        identity = (
            opened.st_dev, opened.st_ino, opened.st_ctime_ns,
            opened.st_mtime_ns, opened.st_size,
        )
        etag = '"' + hashlib.sha256(repr(identity).encode('ascii')).hexdigest() + '"'
        last_modified = formatdate(opened.st_mtime, usegmt=True)
        headers = {
            'Cache-Control': 'no-store',
            'Accept-Ranges': 'bytes',
            'ETag': etag,
            'Last-Modified': last_modified,
        }
        range_header = request.headers.get('range')
        # HTTP-date If-Range is not strong enough for a private master:
        # Last-Modified rounds to seconds, allowing a replaced film to be
        # spliced into an old byte-range download. A mismatch (including
        # any date/weak validator) safely falls back to a complete 200.
        if_range = request.headers.get('if-range')
        if range_header and if_range is not None and if_range != etag:
            range_header = None
        try:
            ranges = (
                _asset_byte_ranges(range_header, opened.st_size)
                if range_header else None
            )
        except ValueError:
            os.close(fd)
            return Response(
                status_code=416,
                headers={
                    'Cache-Control': 'no-store',
                    'Accept-Ranges': 'bytes',
                    'Content-Range': f'bytes */{opened.st_size}',
                },
            )
        # Freeze bytes before response.start: an opened inode can otherwise be
        # rewritten by a concurrent local process while pread is streaming.
        # HEAD does not send a body, so it requires no on-disk snapshot.
        if request.method != 'HEAD':
            try:
                snapshot_fd = _snapshot_private_asset(
                    fd, opened, path.parent, ranges,
                )
            except ValueError as exc:
                raise HTTPException(
                    409, 'Private asset changed while preparing response',
                ) from exc
            except OSError as exc:
                raise HTTPException(
                    503, 'Private asset snapshot unavailable',
                ) from exc
            original_fd, fd = fd, snapshot_fd
            os.close(original_fd)
        return _OpenedAssetResponse(
            fd, opened.st_size, ranges, media_type, headers,
            status_code=206 if ranges else 200,
        )
    except BaseException:
        # The response owns fd only after successful construction.
        # An already-closed 416 descriptor is returned before this handler.
        os.close(fd)
        raise


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


@router.post('/projects/{project_id}/scenes/{scene_id}/shots/{shot_id}/render')
def cinematic_shot_render(
    project_id: str,
    scene_id: str,
    shot_id: str,
    request: ShotRenderRequest,
):
    try:
        return render_shot(project_id, scene_id, shot_id, request)
    except ProjectRevisionConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, 'Cinematic project, scene, or shot not found') from exc
    except (FileNotFoundError, UnsupportedEngineControl, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except EngineUnavailableError as exc:
        raise HTTPException(503, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc



@router.get('/projects/{project_id}/render-status')
def cinematic_project_render_status(project_id: str):
    try:
        return project_render_status(project_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, 'Cinematic project not found') from exc


@router.post('/projects/{project_id}/render-missing')
def cinematic_render_missing(project_id: str, request: BatchRenderRequest):
    try:
        return render_project_missing(project_id, request)
    except ProjectRevisionConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, 'Cinematic project or engine not found') from exc
    except (FileNotFoundError, UnsupportedEngineControl, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except (EngineUnavailableError, RuntimeError) as exc:
        raise HTTPException(503, 'Local render worker unavailable or unable to schedule shot') from exc


@router.get('/projects/{project_id}/masters')
def cinematic_project_masters(project_id: str):
    try:
        get_project(project_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, 'Cinematic project not found') from exc
    return [
        record for record in list_video_records('video_master')
        if record.get('project_id') == project_id
    ]


@router.post('/projects/{project_id}/assemble')
def cinematic_assemble_project(project_id: str, request: AssembleMasterRequest):
    try:
        return assemble_project_master(project_id, request)
    except ProjectRevisionConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except MasterAssemblyNotReady as exc:
        raise HTTPException(409, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, 'Cinematic project not found') from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except (RuntimeError, OSError) as exc:
        raise HTTPException(503, 'Local FFmpeg master assembly failed; check worker diagnostics') from exc


@router.post('/projects/{project_id}/assembly-jobs', status_code=202)
def queue_cinematic_master_assembly(project_id: str, request: AssembleMasterRequest):
    """Return immediately with a durable job ID, never the actual MP4 bytes."""
    try:
        return enqueue_master_assembly(project_id, request)
    except ProjectRevisionConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except MasterAssemblyNotReady as exc:
        raise HTTPException(409, str(exc)) from exc
    except AssemblyQueueFull as exc:
        raise HTTPException(429, str(exc)) from exc
    except FilmDurationExceeded as exc:
        raise HTTPException(422, str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, 'Cinematic project not found') from exc
    except RuntimeError as exc:
        raise HTTPException(503, 'Local assembly worker not available; inspect queued jobs') from exc


@router.get('/projects/{project_id}/assembly-jobs')
def cinematic_assembly_jobs(project_id: str, limit: int = 50, offset: int = 0):
    try:
        get_project(project_id)
        return list_master_assembly_jobs(project_id, limit=limit, offset=offset)
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, 'Cinematic project not found or invalid pagination') from exc


@router.get('/projects/{project_id}/assembly-jobs/{job_id}')
def cinematic_assembly_job(project_id: str, job_id: str):
    try:
        get_project(project_id)
        return get_master_assembly_job(project_id, job_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, 'Cinematic project or assembly job not found') from exc



@router.post('/projects/{project_id}/assembly-jobs/{job_id}/cancel')
def cinematic_cancel_queued_assembly(project_id: str, job_id: str):
    """Cancel only queued work; never imply an active FFmpeg job was stopped."""
    try:
        get_project(project_id)
        return cancel_queued_master_assembly(project_id, job_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, 'Cinematic project or assembly job not found') from exc
    except AssemblyCancellationConflict as exc:
        raise HTTPException(409, str(exc)) from exc


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
