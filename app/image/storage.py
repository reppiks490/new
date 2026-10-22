from __future__ import annotations

from pathlib import Path
import re
from typing import Literal

from app.studio.storage import get, list_records, put, root


ImageRecordKind = Literal['image_job', 'image_asset_meta']
_IMAGE_RECORD_KINDS = frozenset({'image_job', 'image_asset_meta'})
_IMAGE_EXTENSIONS = frozenset({'png', 'json'})
_ID_PATTERN = re.compile(r'^[a-f0-9]{32}$')


def image_asset_path(identifier: str, extension: str) -> Path:
    if not _ID_PATTERN.fullmatch(identifier) or extension not in _IMAGE_EXTENSIONS:
        raise ValueError('Invalid image asset identifier')

    workspace = root().resolve()
    directory = workspace / 'image-assets'
    directory.mkdir(exist_ok=True)
    resolved_directory = directory.resolve()
    if directory.is_symlink() or not resolved_directory.is_relative_to(workspace):
        raise ValueError('Image asset escapes workspace')

    path = directory / f'{identifier}.{extension}'
    if path.is_symlink() or not path.resolve().is_relative_to(resolved_directory):
        raise ValueError('Image asset escapes workspace')
    return path


def _validated_kind(kind: str) -> ImageRecordKind:
    if kind not in _IMAGE_RECORD_KINDS:
        raise ValueError('Invalid image record kind')
    return kind  # type: ignore[return-value]


def put_image_record(kind: ImageRecordKind, data: dict, identifier: str | None = None) -> dict:
    return put(_validated_kind(kind), data, identifier=identifier)


def get_image_record(kind: ImageRecordKind, identifier: str) -> dict:
    return get(_validated_kind(kind), identifier)


def list_image_records(kind: ImageRecordKind) -> list[dict]:
    return list_records(_validated_kind(kind))
