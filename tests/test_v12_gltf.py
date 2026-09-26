import json
import struct
from pathlib import Path

from app.exports.gltf_validation import GLB_JSON_CHUNK, GLB_MAGIC, validate_gltf_structure


def write_minimal_gltf(path: Path, *, buffer_uri: str = 'mesh.bin'):
    doc = {
        'asset': {'version': '2.0'},
        'buffers': [{'byteLength': 4, 'uri': buffer_uri}],
        'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': 4}],
        'accessors': [{'bufferView': 0, 'componentType': 5121, 'count': 4, 'type': 'SCALAR'}],
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0}}]}],
        'nodes': [{'mesh': 0}],
        'scenes': [{'nodes': [0]}],
        'scene': 0,
    }
    path.write_text(json.dumps(doc))


def test_gltf_validates_references_and_external_resource(tmp_path: Path):
    p = tmp_path / 'model.gltf'
    write_minimal_gltf(p)
    (tmp_path / 'mesh.bin').write_bytes(b'1234')
    report = validate_gltf_structure(p)
    assert report.passed
    assert report.mesh_count == 1
    assert report.external_resource_count == 1


def test_gltf_blocks_path_escape_and_bad_index(tmp_path: Path):
    p = tmp_path / 'model.gltf'
    write_minimal_gltf(p, buffer_uri='../secret.bin')
    doc = json.loads(p.read_text())
    doc['nodes'][0]['mesh'] = 9
    p.write_text(json.dumps(doc))
    report = validate_gltf_structure(p)
    assert not report.passed
    assert any('out-of-range' in x for x in report.blockers)
    assert any('escapes' in x for x in report.blockers)


def test_glb_minimal_header_and_json(tmp_path: Path):
    doc = {'asset': {'version': '2.0'}, 'scenes': [{}], 'scene': 0}
    payload = json.dumps(doc, separators=(',', ':')).encode()
    payload += b' ' * ((4 - len(payload) % 4) % 4)
    length = 12 + 8 + len(payload)
    raw = struct.pack('<III', GLB_MAGIC, 2, length) + struct.pack('<II', len(payload), GLB_JSON_CHUNK) + payload
    p = tmp_path / 'model.glb'; p.write_bytes(raw)
    report = validate_gltf_structure(p)
    assert report.parsed
    assert report.passed
