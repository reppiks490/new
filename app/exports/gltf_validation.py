from __future__ import annotations

import json
import struct
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, Field


GLB_MAGIC = 0x46546C67
GLB_JSON_CHUNK = 0x4E4F534A
GLB_BIN_CHUNK = 0x004E4942


class GltfStructuralReport(BaseModel):
    path: str
    format: str
    parsed: bool
    asset_version: str | None = None
    node_count: int = 0
    mesh_count: int = 0
    material_count: int = 0
    image_count: int = 0
    skin_count: int = 0
    animation_count: int = 0
    external_resource_count: int = 0
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.parsed and not self.blockers


def _safe_external_uri(uri: str) -> tuple[bool, str | None]:
    if uri.startswith('data:'):
        return True, None
    parsed = urlparse(uri)
    if parsed.scheme:
        return False, f'External URI uses disallowed scheme: {parsed.scheme}.'
    p = Path(uri)
    if p.is_absolute() or '..' in p.parts:
        return False, 'External URI escapes the package directory.'
    return True, None


def _check_index(value: int | None, size: int, label: str, blockers: list[str]) -> None:
    if value is None:
        return
    if not isinstance(value, int) or value < 0 or value >= size:
        blockers.append(f'{label} references out-of-range index {value}.')


def _load_glb(path: Path) -> tuple[dict, bytes | None]:
    raw = path.read_bytes()
    if len(raw) < 12:
        raise ValueError('GLB file is shorter than the 12-byte header.')
    magic, version, declared_length = struct.unpack_from('<III', raw, 0)
    if magic != GLB_MAGIC:
        raise ValueError('Invalid GLB magic.')
    if version != 2:
        raise ValueError(f'Unsupported GLB version {version}.')
    if declared_length != len(raw):
        raise ValueError(f'GLB declared length {declared_length} does not match file length {len(raw)}.')
    offset = 12
    json_payload: dict | None = None
    bin_payload: bytes | None = None
    chunk_index = 0
    while offset < len(raw):
        if offset + 8 > len(raw):
            raise ValueError('Truncated GLB chunk header.')
        chunk_len, chunk_type = struct.unpack_from('<II', raw, offset)
        offset += 8
        if offset + chunk_len > len(raw):
            raise ValueError('GLB chunk exceeds declared file length.')
        payload = raw[offset:offset + chunk_len]
        offset += chunk_len
        if chunk_index == 0 and chunk_type != GLB_JSON_CHUNK:
            raise ValueError('First GLB chunk must be JSON.')
        if chunk_type == GLB_JSON_CHUNK:
            if json_payload is not None:
                raise ValueError('GLB contains more than one JSON chunk.')
            try:
                json_payload = json.loads(payload.decode('utf-8').rstrip(' \t\r\n\x00'))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f'Invalid GLB JSON chunk: {exc}') from exc
        elif chunk_type == GLB_BIN_CHUNK:
            if bin_payload is not None:
                raise ValueError('GLB contains more than one BIN chunk.')
            bin_payload = payload
        chunk_index += 1
    if json_payload is None:
        raise ValueError('GLB has no JSON chunk.')
    return json_payload, bin_payload


def _load_gltf(path: Path) -> tuple[dict, bytes | None]:
    try:
        return json.loads(path.read_text(encoding='utf-8')), None
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f'Invalid glTF JSON: {exc}') from exc


def validate_gltf_structure(path: str | Path) -> GltfStructuralReport:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(p)
    fmt = p.suffix.lower().lstrip('.')
    if fmt not in {'gltf', 'glb'}:
        raise ValueError('validate_gltf_structure supports only .gltf and .glb')
    try:
        doc, bin_payload = _load_glb(p) if fmt == 'glb' else _load_gltf(p)
    except ValueError as exc:
        return GltfStructuralReport(path=str(p), format=fmt, parsed=False, blockers=[str(exc)])

    blockers: list[str] = []
    warnings: list[str] = []
    asset = doc.get('asset') or {}
    version = asset.get('version')
    if version != '2.0':
        blockers.append(f'glTF asset.version must be 2.0, got {version!r}.')

    nodes = doc.get('nodes') or []
    meshes = doc.get('meshes') or []
    accessors = doc.get('accessors') or []
    buffer_views = doc.get('bufferViews') or []
    buffers = doc.get('buffers') or []
    materials = doc.get('materials') or []
    images = doc.get('images') or []
    textures = doc.get('textures') or []
    samplers = doc.get('samplers') or []
    skins = doc.get('skins') or []
    animations = doc.get('animations') or []
    scenes = doc.get('scenes') or []
    cameras = doc.get('cameras') or []

    for i, node in enumerate(nodes):
        _check_index(node.get('mesh'), len(meshes), f'nodes[{i}].mesh', blockers)
        _check_index(node.get('skin'), len(skins), f'nodes[{i}].skin', blockers)
        _check_index(node.get('camera'), len(cameras), f'nodes[{i}].camera', blockers)
        for child in node.get('children') or []:
            _check_index(child, len(nodes), f'nodes[{i}].children', blockers)

    for mi, mesh in enumerate(meshes):
        for pi, prim in enumerate(mesh.get('primitives') or []):
            _check_index(prim.get('indices'), len(accessors), f'meshes[{mi}].primitives[{pi}].indices', blockers)
            _check_index(prim.get('material'), len(materials), f'meshes[{mi}].primitives[{pi}].material', blockers)
            for semantic, accessor_idx in (prim.get('attributes') or {}).items():
                _check_index(accessor_idx, len(accessors), f'meshes[{mi}].primitives[{pi}].attributes[{semantic}]', blockers)
            for ti, target in enumerate(prim.get('targets') or []):
                for semantic, accessor_idx in target.items():
                    _check_index(accessor_idx, len(accessors), f'meshes[{mi}].primitives[{pi}].targets[{ti}][{semantic}]', blockers)

    for ai, accessor in enumerate(accessors):
        _check_index(accessor.get('bufferView'), len(buffer_views), f'accessors[{ai}].bufferView', blockers)
        if accessor.get('count', 0) < 0:
            blockers.append(f'accessors[{ai}].count is negative.')

    for bi, view in enumerate(buffer_views):
        _check_index(view.get('buffer'), len(buffers), f'bufferViews[{bi}].buffer', blockers)

    external_resources = 0
    for bi, buffer in enumerate(buffers):
        uri = buffer.get('uri')
        byte_length = int(buffer.get('byteLength') or 0)
        if byte_length <= 0:
            blockers.append(f'buffers[{bi}].byteLength must be positive.')
        if uri:
            ok, reason = _safe_external_uri(uri)
            if not ok:
                blockers.append(f'buffers[{bi}]: {reason}')
            elif not uri.startswith('data:'):
                external_resources += 1
                target = (p.parent / uri).resolve()
                try:
                    target.relative_to(p.parent.resolve())
                except ValueError:
                    blockers.append(f'buffers[{bi}] resolves outside the package directory.')
                else:
                    if not target.is_file():
                        blockers.append(f'buffers[{bi}] external resource is missing: {uri}.')
                    elif target.stat().st_size < byte_length:
                        blockers.append(f'buffers[{bi}] external resource is shorter than byteLength.')
        elif fmt == 'glb':
            if bi == 0 and bin_payload is not None and len(bin_payload) < byte_length:
                blockers.append('GLB BIN chunk is shorter than buffers[0].byteLength.')
        else:
            blockers.append(f'buffers[{bi}] has no URI in a .gltf file.')

    for ii, image in enumerate(images):
        if 'uri' in image:
            uri = str(image['uri'])
            ok, reason = _safe_external_uri(uri)
            if not ok:
                blockers.append(f'images[{ii}]: {reason}')
            elif not uri.startswith('data:'):
                external_resources += 1
                target = (p.parent / uri).resolve()
                try:
                    target.relative_to(p.parent.resolve())
                except ValueError:
                    blockers.append(f'images[{ii}] resolves outside the package directory.')
                else:
                    if not target.is_file():
                        blockers.append(f'images[{ii}] external resource is missing: {uri}.')
        elif 'bufferView' in image:
            _check_index(image.get('bufferView'), len(buffer_views), f'images[{ii}].bufferView', blockers)
        else:
            blockers.append(f'images[{ii}] has neither uri nor bufferView.')

    for ti, texture in enumerate(textures):
        _check_index(texture.get('source'), len(images), f'textures[{ti}].source', blockers)
        _check_index(texture.get('sampler'), len(samplers), f'textures[{ti}].sampler', blockers)

    for si, skin in enumerate(skins):
        joints = skin.get('joints') or []
        if not joints:
            blockers.append(f'skins[{si}] has no joints.')
        for joint in joints:
            _check_index(joint, len(nodes), f'skins[{si}].joints', blockers)
        _check_index(skin.get('skeleton'), len(nodes), f'skins[{si}].skeleton', blockers)
        _check_index(skin.get('inverseBindMatrices'), len(accessors), f'skins[{si}].inverseBindMatrices', blockers)

    for ai, animation in enumerate(animations):
        animation_samplers = animation.get('samplers') or []
        for si, sampler in enumerate(animation_samplers):
            _check_index(sampler.get('input'), len(accessors), f'animations[{ai}].samplers[{si}].input', blockers)
            _check_index(sampler.get('output'), len(accessors), f'animations[{ai}].samplers[{si}].output', blockers)
        for ci, channel in enumerate(animation.get('channels') or []):
            _check_index(channel.get('sampler'), len(animation_samplers), f'animations[{ai}].channels[{ci}].sampler', blockers)
            target = channel.get('target') or {}
            _check_index(target.get('node'), len(nodes), f'animations[{ai}].channels[{ci}].target.node', blockers)
            if target.get('path') not in {'translation', 'rotation', 'scale', 'weights'}:
                blockers.append(f'animations[{ai}].channels[{ci}].target.path is invalid: {target.get("path")!r}.')

    for si, scene in enumerate(scenes):
        for node_index in scene.get('nodes') or []:
            _check_index(node_index, len(nodes), f'scenes[{si}].nodes', blockers)
    _check_index(doc.get('scene'), len(scenes), 'scene', blockers)

    used = set(doc.get('extensionsUsed') or [])
    required = set(doc.get('extensionsRequired') or [])
    if not required.issubset(used):
        blockers.append('extensionsRequired contains entries not listed in extensionsUsed.')
    if not meshes:
        warnings.append('glTF contains no meshes.')

    return GltfStructuralReport(
        path=str(p), format=fmt, parsed=True, asset_version=version,
        node_count=len(nodes), mesh_count=len(meshes), material_count=len(materials), image_count=len(images),
        skin_count=len(skins), animation_count=len(animations), external_resource_count=external_resources,
        blockers=blockers, warnings=warnings,
    )
