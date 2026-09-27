"""Lightweight stand-in for a dense terrain GLB (pure Python, no bpy).

When a terrain carries a base-grid displacement sidecar the render worker
throws the imported mesh away and rebuilds it from the sidecar, so importing
33.5M triangles only to delete them is waste -- and on a 16 GB box it is the
step that got the process OOM-killed (measured 12.9 GB peak). The proxy keeps
the original JSON (materials, textures, samplers, node transform) and the
image bytes, streamed unchanged, but replaces the geometry with one quad
spanning the original POSITION accessor's min/max, so footprint checks and
material binding behave exactly as with the full asset.
"""
from __future__ import annotations

import copy
import json
import struct
from pathlib import Path

GLB_MAGIC, JSON_CHUNK, BIN_CHUNK = 0x46546C67, 0x4E4F534A, 0x004E4942
FLOAT, UINT32 = 5126, 5125


def _pad4(n: int) -> int:
    return (4 - n % 4) % 4


def read_glb_json(path: str | Path) -> tuple[dict, int]:
    """Returns (gltf json, absolute file offset of the BIN chunk's data)."""
    with open(path, 'rb') as fh:
        magic, _version, _length = struct.unpack('<III', fh.read(12))
        if magic != GLB_MAGIC:
            raise ValueError(f'{path} is not a GLB')
        jlen, jtype = struct.unpack('<II', fh.read(8))
        if jtype != JSON_CHUNK:
            raise ValueError('first GLB chunk is not JSON')
        gltf = json.loads(fh.read(jlen))
        return gltf, 12 + 8 + jlen + 8


def write_terrain_proxy(src: str | Path, dst: str | Path) -> dict | None:
    """Returns stats, or None when the GLB is not a single-primitive mesh
    (then the caller imports the real file)."""
    gltf, bin_start = read_glb_json(src)
    meshes = gltf.get('meshes', [])
    if len(meshes) != 1 or len(meshes[0].get('primitives', [])) != 1 or len(gltf.get('buffers', [])) != 1:
        return None
    prim = meshes[0]['primitives'][0]
    pos = gltf['accessors'][prim['attributes']['POSITION']]
    if 'min' not in pos or 'max' not in pos:
        return None
    (x0, y0, z0), (x1, y1, z1) = pos['min'], pos['max']
    ym = (y0 + y1) / 2
    positions = [x0, ym, z0, x1, ym, z0, x1, ym, z1, x0, ym, z1]
    geometry = [
        (struct.pack('<12f', *positions), 34962, {'componentType': FLOAT, 'count': 4, 'type': 'VEC3',
                                                  'min': [x0, ym, z0], 'max': [x1, ym, z1]}),
        (struct.pack('<12f', *[0, 1, 0] * 4), 34962, {'componentType': FLOAT, 'count': 4, 'type': 'VEC3'}),
        (struct.pack('<8f', 0, 1, 1, 1, 1, 0, 0, 0), 34962, {'componentType': FLOAT, 'count': 4, 'type': 'VEC2'}),
        (struct.pack('<6I', 0, 2, 1, 0, 3, 2), 34963, {'componentType': UINT32, 'count': 6, 'type': 'SCALAR'}),
    ]
    out = copy.deepcopy(gltf)
    views, parts, offset = [], [], 0
    for data, target, acc in geometry:
        views.append({'buffer': 0, 'byteOffset': offset, 'byteLength': len(data), 'target': target})
        parts.append(('bytes', data))
        offset += len(data) + _pad4(len(data))
    accessors = [dict(acc, bufferView=i) for i, (_, _, acc) in enumerate(geometry)]
    for img in out.get('images', []):
        if 'bufferView' not in img:
            continue
        v = gltf['bufferViews'][img['bufferView']]
        img['bufferView'] = len(views)
        views.append({'buffer': 0, 'byteOffset': offset, 'byteLength': v['byteLength']})
        parts.append(('copy', (bin_start + v.get('byteOffset', 0), v['byteLength'])))
        offset += v['byteLength'] + _pad4(v['byteLength'])
    new_prim = {k: v for k, v in prim.items() if k not in ('attributes', 'indices', 'targets')}
    new_prim.update(attributes={'POSITION': 0, 'NORMAL': 1, 'TEXCOORD_0': 2}, indices=3, mode=4)
    out['meshes'][0]['primitives'] = [new_prim]
    out['accessors'], out['bufferViews'], out['buffers'] = accessors, views, [{'byteLength': offset}]
    jb = json.dumps(out, separators=(',', ':')).encode()
    jb += b' ' * _pad4(len(jb))
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(src, 'rb') as s, open(dst, 'wb') as d:
        d.write(struct.pack('<III', GLB_MAGIC, 2, 12 + 8 + len(jb) + 8 + offset))
        d.write(struct.pack('<II', len(jb), JSON_CHUNK) + jb)
        d.write(struct.pack('<II', offset, BIN_CHUNK))
        for kind, payload in parts:
            if kind == 'bytes':
                d.write(payload + b'\0' * _pad4(len(payload)))
                continue
            start, length = payload
            s.seek(start)
            left = length
            while left:
                chunk = s.read(min(left, 16 << 20))
                d.write(chunk)
                left -= len(chunk)
            d.write(b'\0' * _pad4(length))
    return {'source_triangles': gltf['accessors'][prim['indices']]['count'] // 3 if 'indices' in prim else None,
            'proxy_bytes': dst.stat().st_size}
