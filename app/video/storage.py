from __future__ import annotations

from pathlib import Path
import re
from typing import Literal

from app.studio.storage import get, list_records, put, root


VideoRecordKind = Literal['video_job', 'video_privacy', 'video_asset_meta', 'video_project']
_VIDEO_RECORD_KINDS = frozenset({'video_job', 'video_privacy', 'video_asset_meta', 'video_project'})
_VIDEO_EXTENSIONS = frozenset({'png', 'mp4', 'json'})
_ID_PATTERN = re.compile(r'^[a-f0-9]{32}$')


def video_asset_path(identifier: str, extension: str) -> Path:
    if not _ID_PATTERN.fullmatch(identifier) or extension not in _VIDEO_EXTENSIONS:
        raise ValueError('Invalid video asset identifier')

    workspace = root().resolve()
    directory = workspace / 'video-assets'
    directory.mkdir(exist_ok=True)
    resolved_directory = directory.resolve()
    if directory.is_symlink() or not resolved_directory.is_relative_to(workspace):
        raise ValueError('Video asset escapes workspace')

    path = directory / f'{identifier}.{extension}'
    if path.is_symlink() or not path.resolve().is_relative_to(resolved_directory):
        raise ValueError('Video asset escapes workspace')
    return path


def _validated_kind(kind: str) -> VideoRecordKind:
    if kind not in _VIDEO_RECORD_KINDS:
        raise ValueError('Invalid video record kind')
    return kind  # type: ignore[return-value]


def put_video_record(kind: VideoRecordKind, data: dict, identifier: str | None = None) -> dict:
    return put(_validated_kind(kind), data, identifier=identifier)


def get_video_record(kind: VideoRecordKind, identifier: str) -> dict:
    return get(_validated_kind(kind), identifier)


def list_video_records(kind: VideoRecordKind) -> list[dict]:
    return list_records(_validated_kind(kind))
