"""Private, lossless registration of user-provided self-contained GLB models.

Registration is a local operation. HTTP consumers receive identifiers and
metadata, never a filesystem path or an endpoint accepting one.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time

from app.exports.gltf_validation import _load_glb, validate_gltf_structure
from app.studio import storage


MAX_MODEL_BYTES = 150 * 1024 * 1024
_ID = re.compile(r'[a-f0-9]{32}')
_COMPONENT_BYTES = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
_TYPE_WIDTH = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT2': 4, 'MAT3': 9, 'MAT4': 16}
_DECODERS = {'KHR_draco_mesh_compression', 'EXT_meshopt_compression', 'KHR_texture_basisu'}


def _text(value, limit=200):
    if not isinstance(value, str):
        return ''
    return ''.join(c for c in value if c.isprintable()).strip()[:limit]


def _digest(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _reject_external_uris(value):
    # Includes URI-bearing extensions, not only core buffers and images.
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'uri' and (not isinstance(item, str) or not item.startswith('data:')):
                raise ValueError('Model must be self-contained; external resource URIs are not allowed')
            _reject_external_uris(item)
    elif isinstance(value, list):
        for item in value:
            _reject_external_uris(item)


def _nonnegative_int(value, label):
    if type(value) is not int or value < 0:
        raise ValueError(f'{label} must be a nonnegative integer')
    return value


def _validate_layout(doc, bin_length):
    """Check binary boundaries omitted by the shared structural inspector."""
    buffers = doc.get('buffers', [])
    for index, buffer in enumerate(buffers):
        if not buffer.get('uri'):
            if index != 0 or bin_length is None:
                raise ValueError('GLB buffer is missing its binary payload')
            if buffer['byteLength'] > bin_length:
                raise ValueError('GLB buffer exceeds its binary payload')
    views = doc.get('bufferViews', [])
    for view in views:
        offset = _nonnegative_int(view.get('byteOffset', 0), 'Buffer view offset')
        length = _nonnegative_int(view.get('byteLength'), 'Buffer view length')
        if offset + length > buffers[view['buffer']]['byteLength']:
            raise ValueError('Buffer view exceeds its buffer')
    for accessor in doc.get('accessors', []):
        count = _nonnegative_int(accessor.get('count'), 'Accessor count')
        component = _COMPONENT_BYTES.get(accessor.get('componentType'))
        width = _TYPE_WIDTH.get(accessor.get('type'))
        if not component or not width:
            raise ValueError('Accessor has an unsupported component type or shape')
        if 'bufferView' not in accessor:
            continue  # Zero-initialized or sparse accessors are valid glTF.
        view = views[accessor['bufferView']]
        offset = _nonnegative_int(accessor.get('byteOffset', 0), 'Accessor offset')
        # Small matrix components pad each column to four-byte alignment.
        shape = accessor['type']
        columns = int(shape[-1]) if shape.startswith('MAT') else 1
        element_bytes = (((columns * component + 3) // 4) * 4 * columns
                         if columns > 1 else width * component)
        stride = _nonnegative_int(view.get('byteStride', element_bytes), 'Accessor stride')
        if stride < element_bytes:
            raise ValueError('Accessor stride is smaller than its element')
        required = offset + (count - 1) * stride + element_bytes if count else offset
        if required > view['byteLength']:
            raise ValueError('Accessor exceeds its buffer view')


def inspect_model(path: str | Path) -> dict:
    """Inspect without re-exporting geometry, skinning, animation, or materials."""
    path = Path(path)
    if path.suffix.lower() != '.glb':
        raise ValueError('Register a .glb file; convert .blend sources to self-contained GLB first')
    if not path.is_file():
        raise ValueError('Model file does not exist')
    size = path.stat().st_size
    if size > MAX_MODEL_BYTES:
        raise ValueError('Model exceeds the 150 MiB limit')
    try:
        # Parse first so external resources are rejected before the shared
        # validator considers following a relative resource on the filesystem.
        doc, binary = _load_glb(path)
        if not isinstance(doc, dict):
            raise ValueError('GLB JSON must contain an object')
        _reject_external_uris(doc)
        bin_length = len(binary) if binary is not None else None
        del binary
        report = validate_gltf_structure(path)
        if not report.passed:
            raise ValueError('Invalid GLB structure: ' + '; '.join(report.blockers))
        _validate_layout(doc, bin_length)
        meshes, accessors = doc.get('meshes', []), doc.get('accessors', [])
        if not meshes:
            raise ValueError('Model has no meshes')
        primitive_count = triangle_count = morph_count = 0
        morph_names = []
        for mi, mesh in enumerate(meshes):
            target_names = (mesh.get('extras') or {}).get('targetNames', [])
            mesh_morph_count = 0
            for primitive in mesh.get('primitives', []):
                primitive_count += 1
                position = primitive.get('attributes', {}).get('POSITION')
                if position is None or accessors[position]['count'] <= 0:
                    raise ValueError('Model primitive has no nonempty POSITION accessor')
                accessor = accessors[primitive.get('indices', position)]
                count, mode = accessor['count'], primitive.get('mode', 4)
                triangle_count += count // 3 if mode == 4 else max(count - 2, 0) if mode in {5, 6} else 0
                mesh_morph_count = max(mesh_morph_count, len(primitive.get('targets', [])))
            morph_count += mesh_morph_count
            for ti in range(mesh_morph_count):
                label = _text(target_names[ti]) if ti < len(target_names) else ''
                morph_names.append(label or f'Mesh {mi + 1} · target {ti + 1}')
        if not primitive_count:
            raise ValueError('Model has no mesh primitives')
        animations = doc.get('animations', [])
        extras = doc.get('asset', {}).get('extras') or {}
        credit = doc.get('asset', {}).get('copyright') or (
            extras.get('author') or extras.get('credit') if isinstance(extras, dict) else '')
        decoder_requirements = sorted(set(doc.get('extensionsRequired', [])) & _DECODERS)
        return {
            'bytes': size, 'mesh_count': len(meshes), 'primitive_count': primitive_count,
            'triangle_count': triangle_count, 'material_count': len(doc.get('materials', [])),
            'image_count': len(doc.get('images', [])), 'skin_count': len(doc.get('skins', [])),
            'animation_count': len(animations),
            'animation_names': [_text(a.get('name')) or f'Animation {i + 1}' for i, a in enumerate(animations)],
            'morph_target_count': morph_count, 'morph_target_names': morph_names,
            'source_credit': _text(credit, 2000) or None,
            'license_status': 'user-provided; unverified',
            'readiness': {
                'geometry': 'preserved', 'rig': 'present' if doc.get('skins') else 'absent',
                'animations': 'present' if animations else 'absent',
                'morphs': 'present' if morph_count else 'absent',
                'rendering': 'unverified', 'decoder_requirements': decoder_requirements,
                'warnings': report.warnings,
            },
        }
    except (ValueError, TypeError, AttributeError, KeyError, IndexError, RecursionError) as exc:
        raise ValueError(f'Cannot register model: {exc}') from exc


def register_model(path: str | Path, *, name: str | None = None, source_credit: str | None = None) -> dict:
    """Copy, inspect, and atomically register original bytes; identical imports share an ID."""
    source = Path(path)
    if source.suffix.lower() != '.glb' or not source.is_file():
        raise ValueError('Use an existing .glb file; convert .blend sources first')
    if source.stat().st_size > MAX_MODEL_BYTES:
        raise ValueError('Model exceeds the 150 MiB limit')
    directory = storage.asset_path('0' * 32).parent
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix='.import-', suffix='.glb', delete=False) as stream:
            temporary = Path(stream.name)
            digest, size = hashlib.sha256(), 0
            with source.open('rb') as incoming:
                for block in iter(lambda: incoming.read(1024 * 1024), b''):
                    size += len(block)
                    if size > MAX_MODEL_BYTES:
                        raise ValueError('Model exceeds the 150 MiB limit')
                    digest.update(block)
                    stream.write(block)
        metadata = inspect_model(temporary)
        sha256 = digest.hexdigest()
        identifier = sha256[:32]
        with storage.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT kind,data FROM records WHERE id=?', (identifier,)).fetchone()
            if existing:
                previous = json.loads(existing[1])
                if existing[0] != 'model' or previous.get('sha256') != sha256:
                    raise ValueError('Model identifier conflicts with an existing record')
                metadata = previous
            else:
                metadata.update(name=_text(name) or _text(source.stem) or 'Imported model',
                                source_filename=_text(source.name), sha256=sha256,
                                asset_url=f'/api/studio/assets/{identifier}.glb')
            if source_credit is not None:
                metadata['source_credit'] = _text(source_credit, 2000) or None
            if name is not None:
                metadata['name'] = _text(name) or metadata['name']
            destination = storage.asset_path(identifier)
            if destination.exists():
                if _digest(destination) != sha256:
                    raise ValueError('Stored model bytes differ from their recorded SHA-256; import stopped')
            else:
                os.replace(temporary, destination)
            db.execute('INSERT INTO records VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated=excluded.updated',
                       (identifier, 'model', json.dumps(metadata, allow_nan=False), time.time()))
        return {'id': identifier, **metadata}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def list_models() -> list[dict]:
    return storage.list_records('model')


def get_model(identifier: str) -> dict:
    if not _ID.fullmatch(identifier):
        raise KeyError(identifier)
    return storage.get('model', identifier)
