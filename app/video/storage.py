from __future__ import annotations

from pathlib import Path
import re

from app.studio import storage as studio_storage


_ALLOWED_EXTENSIONS = {'png', 'mp4', 'json'}
_ALLOWED_KINDS = {'video_job', 'video_privacy', 'video_asset_meta'}
_ID_PATTERN = re.compile(r'^[a-f0-9]{32}$')


def video_asset_path(identifier: str, extension: str) -> Path:
    if not _ID_PATTERN.fullmatch(identifier):
        raise ValueError('Invalid video asset identifier')
    if extension not in _ALLOWED_EXTENSIONS:
        raise ValueError('Unsupported video asset extension')

    directory = studio_storage.root() / 'video-assets'
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink():
        raise ValueError('Video asset directory cannot be a symlink')

    path = directory / f'{identifier}.{extension}'
    resolved_directory = directory.resolve()
    resolved_path = path.resolve(strict=False)
    if not resolved_path.is_relative_to(resolved_directory) or path.is_symlink():
        raise ValueError('Video asset escapes workspace')
    return path


def _validate_kind(kind: str) -> None:
    if kind not in _ALLOWED_KINDS:
        raise ValueError('Unsupported video record kind')


def put_video_record(kind: str, data: dict, identifier: str | None = None) -> dict:
    _validate_kind(kind)
    return studio_storage.put(kind, data, identifier)


def get_video_record(kind: str, identifier: str) -> dict:
    _validate_kind(kind)
    return studio_storage.get(kind, identifier)


def list_video_records(kind: str) -> list[dict]:
    _validate_kind(kind)
    return studio_storage.list_records(kind)
