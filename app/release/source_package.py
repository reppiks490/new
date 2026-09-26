from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, Field

from app.release.reproducibility import FileDigest, sha256_file


DEFAULT_EXCLUDED_PARTS = {
    '.git', '.hg', '.svn', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache',
    '.venv', 'venv', 'node_modules',
}


class SourceReleaseManifest(BaseModel):
    schema_version: str = 'character3d-source-release-v1'
    project: str = 'character3d-masterbuild'
    version: str
    source_digest_sha256: str
    file_count: int
    total_bytes: int
    files: list[FileDigest] = Field(default_factory=list)


def _digest(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str).encode('utf-8')).hexdigest()


def _source_files(root: Path, *, exclude_names: Iterable[str] = ('release_manifest.json',)) -> list[Path]:
    exclude_name_set = set(exclude_names)
    files = []
    for p in sorted(root.rglob('*')):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in DEFAULT_EXCLUDED_PARTS for part in rel.parts[:-1]):
            continue
        if rel.name in exclude_name_set:
            continue
        files.append(p)
    return files


def build_source_release_manifest(root: str | Path, *, version: str) -> SourceReleaseManifest:
    root = Path(root).resolve()
    files = []
    for p in _source_files(root):
        rel = p.relative_to(root).as_posix()
        files.append(FileDigest(path=rel, size_bytes=p.stat().st_size, sha256=sha256_file(p)))
    canonical = [x.model_dump(mode='json') for x in files]
    digest = _digest({'project': 'character3d-masterbuild', 'version': version, 'files': canonical})
    return SourceReleaseManifest(
        version=version,
        source_digest_sha256=digest,
        file_count=len(files),
        total_bytes=sum(x.size_bytes for x in files),
        files=files,
    )


def write_source_release_manifest(root: str | Path, *, version: str, filename: str = 'release_manifest.json') -> Path:
    root = Path(root).resolve()
    manifest = build_source_release_manifest(root, version=version)
    out = root / filename
    out.write_text(json.dumps(manifest.model_dump(mode='json'), indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return out


def verify_source_release_manifest(root: str | Path, manifest: SourceReleaseManifest) -> bool:
    current = build_source_release_manifest(root, version=manifest.version)
    return current.source_digest_sha256 == manifest.source_digest_sha256 and current.files == manifest.files


def build_deterministic_zip(root: str | Path, output_path: str | Path) -> Path:
    root = Path(root).resolve()
    output = Path(output_path).resolve()
    files = []
    for p in sorted(root.rglob('*')):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in DEFAULT_EXCLUDED_PARTS for part in rel.parts[:-1]):
            continue
        # Avoid accidentally packaging the destination when output is inside root.
        if p.resolve() == output:
            continue
        files.append((p, rel.as_posix()))
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for src, rel in files:
            info = zipfile.ZipInfo(rel, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.flag_bits |= 0x800
            zf.writestr(info, src.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return output
