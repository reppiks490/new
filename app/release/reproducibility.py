from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel, Field


DEFAULT_IGNORED_DIRS = {
    '.git', '.hg', '.svn', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache',
    '.venv', 'venv', 'node_modules',
}
DEFAULT_IGNORED_FILES = {'.DS_Store', 'Thumbs.db'}


class FileDigest(BaseModel):
    path: str
    size_bytes: int
    sha256: str


class BuildFingerprint(BaseModel):
    schema_version: str = 'character3d-build-fingerprint-v1'
    root_digest_sha256: str
    file_count: int
    total_bytes: int
    files: list[FileDigest]
    metadata: dict[str, Any] = Field(default_factory=dict)


class BuildFingerprintDiff(BaseModel):
    identical: bool
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    changed: list[str] = Field(default_factory=list)
    unchanged_count: int = 0
    baseline_digest: str
    current_digest: str


class RuntimeEnvironmentSnapshot(BaseModel):
    python_version: str
    implementation: str
    platform: str
    machine: str
    byteorder: str
    executable_name: str
    selected_env: dict[str, str] = Field(default_factory=dict)


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(chunk_size), b''):
            h.update(chunk)
    return h.hexdigest()


def _canonical_digest(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def inventory_tree(
    root: str | Path,
    *,
    ignored_dirs: Iterable[str] = DEFAULT_IGNORED_DIRS,
    ignored_files: Iterable[str] = DEFAULT_IGNORED_FILES,
) -> list[FileDigest]:
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        raise NotADirectoryError(root_path)
    ignored_dir_set = set(ignored_dirs)
    ignored_file_set = set(ignored_files)
    out: list[FileDigest] = []
    for path in sorted(root_path.rglob('*')):
        if not path.is_file():
            continue
        rel = path.relative_to(root_path)
        if any(part in ignored_dir_set for part in rel.parts[:-1]):
            continue
        if rel.name in ignored_file_set:
            continue
        stat = path.stat()
        out.append(FileDigest(path=rel.as_posix(), size_bytes=stat.st_size, sha256=sha256_file(path)))
    return out


def compile_build_fingerprint(root: str | Path, *, metadata: dict[str, Any] | None = None) -> BuildFingerprint:
    files = inventory_tree(root)
    canonical_files = [f.model_dump(mode='json') for f in files]
    meta = dict(metadata or {})
    payload = {'files': canonical_files, 'metadata': meta}
    return BuildFingerprint(
        root_digest_sha256=_canonical_digest(payload),
        file_count=len(files),
        total_bytes=sum(f.size_bytes for f in files),
        files=files,
        metadata=meta,
    )


def verify_build_fingerprint(root: str | Path, expected: BuildFingerprint) -> bool:
    current = compile_build_fingerprint(root, metadata=expected.metadata)
    return current.root_digest_sha256 == expected.root_digest_sha256


def compare_build_fingerprints(baseline: BuildFingerprint, current: BuildFingerprint) -> BuildFingerprintDiff:
    a = {f.path: f for f in baseline.files}
    b = {f.path: f for f in current.files}
    added = sorted(set(b) - set(a))
    removed = sorted(set(a) - set(b))
    changed = sorted(p for p in set(a) & set(b) if (a[p].sha256, a[p].size_bytes) != (b[p].sha256, b[p].size_bytes))
    unchanged = len(set(a) & set(b)) - len(changed)
    return BuildFingerprintDiff(
        identical=not added and not removed and not changed and baseline.root_digest_sha256 == current.root_digest_sha256,
        added=added,
        removed=removed,
        changed=changed,
        unchanged_count=unchanged,
        baseline_digest=baseline.root_digest_sha256,
        current_digest=current.root_digest_sha256,
    )


def capture_runtime_environment(*, env_keys: Iterable[str] = ('PYTHONHASHSEED', 'SOURCE_DATE_EPOCH')) -> RuntimeEnvironmentSnapshot:
    selected = {k: os.environ[k] for k in env_keys if k in os.environ}
    return RuntimeEnvironmentSnapshot(
        python_version=platform.python_version(),
        implementation=platform.python_implementation(),
        platform=platform.platform(),
        machine=platform.machine(),
        byteorder=sys.byteorder,
        executable_name=Path(sys.executable).name,
        selected_env=selected,
    )
