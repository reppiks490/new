import hashlib
import json
from pathlib import Path
import struct

from fastapi.testclient import TestClient
import pytest

from app.studio import model_library, storage
from app.studio.server import app


@pytest.fixture(autouse=True)
def isolated_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv('CHARACTER3D_STUDIO_WORKSPACE', str(tmp_path / 'private-workspace'))
    monkeypatch.delenv('CHARACTER3D_STUDIO_TOKEN', raising=False)


def glb_file(tmp_path, mutate=None, filename='character.glb'):
    binary = bytearray()
    views, accessors = [], []

    def accessor(values, component_type, shape, count):
        while len(binary) % 4:
            binary.append(0)
        view = len(views)
        views.append({'buffer': 0, 'byteOffset': len(binary), 'byteLength': len(values)})
        binary.extend(values)
        index = len(accessors)
        accessors.append({'bufferView': view, 'componentType': component_type, 'type': shape, 'count': count})
        return index

    position = accessor(struct.pack('<9f', 0, 0, 0, 1, 0, 0, 0, 1, 0), 5126, 'VEC3', 3)
    uv = accessor(struct.pack('<6f', 0, 0, 1, 0, 0, 1), 5126, 'VEC2', 3)
    indices = accessor(struct.pack('<3H', 0, 1, 2), 5123, 'SCALAR', 3)
    morph = accessor(struct.pack('<9f', *([0.1] * 9)), 5126, 'VEC3', 3)
    joints = accessor(bytes(12), 5121, 'VEC4', 3)
    weights = accessor(struct.pack('<12f', *([1, 0, 0, 0] * 3)), 5126, 'VEC4', 3)
    times = accessor(struct.pack('<2f', 0, 1), 5126, 'SCALAR', 2)
    translation = accessor(struct.pack('<6f', 0, 0, 0, 0, 1, 0), 5126, 'VEC3', 2)
    doc = {
        'asset': {'version': '2.0', 'copyright': 'Example artist'},
        'scene': 0, 'scenes': [{'nodes': [0, 1]}],
        'nodes': [{'mesh': 0, 'skin': 0}, {'name': 'Root joint'}],
        'meshes': [{'name': 'Figure', 'extras': {'targetNames': ['Expression']}, 'weights': [0],
                    'primitives': [{'attributes': {'POSITION': position, 'TEXCOORD_0': uv, 'JOINTS_0': joints, 'WEIGHTS_0': weights},
                                    'indices': indices, 'material': 0, 'targets': [{'POSITION': morph}]}]}],
        'materials': [{'name': 'Cloth', 'pbrMetallicRoughness': {'roughnessFactor': 0.8}}],
        'skins': [{'joints': [1], 'skeleton': 1}],
        'animations': [{'name': 'Idle', 'samplers': [{'input': times, 'output': translation}],
                        'channels': [{'sampler': 0, 'target': {'node': 1, 'path': 'translation'}}]}],
        'buffers': [{'byteLength': len(binary)}], 'bufferViews': views, 'accessors': accessors,
    }
    if mutate:
        mutate(doc)
    payload = json.dumps(doc, separators=(',', ':')).encode()
    payload += b' ' * (-len(payload) % 4)
    binary += b'\0' * (-len(binary) % 4)
    raw = (struct.pack('<III', 0x46546C67, 2, 28 + len(payload) + len(binary))
           + struct.pack('<II', len(payload), 0x4E4F534A) + payload
           + struct.pack('<II', len(binary), 0x004E4942) + binary)
    path = tmp_path / filename
    path.write_bytes(raw)
    return path


def test_registration_preserves_original_binary_rig_morphs_animation_and_materials(tmp_path):
    source = glb_file(tmp_path)
    original = source.read_bytes()
    model = model_library.register_model(source, name='Example character')
    saved = storage.asset_path(model['id'])
    assert saved.read_bytes() == original
    assert model['sha256'] == hashlib.sha256(original).hexdigest()
    assert model['bytes'] == len(original)
    assert model['name'] == 'Example character'
    assert model['mesh_count'] == model['triangle_count'] == model['material_count'] == 1
    assert model['skin_count'] == model['animation_count'] == model['morph_target_count'] == 1
    assert model['animation_names'] == ['Idle']
    assert model['morph_target_names'] == ['Expression']
    assert model['source_credit'] == 'Example artist'
    assert model['license_status'] == 'user-provided; unverified'
    assert model['readiness']['rendering'] == 'unverified'
    assert model['editing']['semantic_regions'] == []
    assert model['editing']['source_morphs'][0] == {
        'mesh_index': 0, 'name': 'Expression', 'mapping_status': 'unmapped'
    }
    assert model['uv_set_count'] == 1
    assert model['uv_sets'] == ['TEXCOORD_0']
    assert model['joint_attribute_sets'] == ['JOINTS_0']
    assert model['skin_joint_counts'] == [1]
    source.write_bytes(b'changed after registration')
    assert saved.read_bytes() == original


def test_static_model_without_morphs_does_not_claim_semantic_editing(tmp_path):
    def make_static(doc):
        primitive=doc['meshes'][0]['primitives'][0]
        primitive.pop('targets')
        primitive['attributes'].pop('JOINTS_0')
        primitive['attributes'].pop('WEIGHTS_0')
        doc['meshes'][0].pop('extras')
        doc['nodes'][0].pop('skin')
        doc['skins']=[]
        doc['animations']=[]
    model=model_library.register_model(glb_file(tmp_path, make_static))
    assert model['skin_count']==0 and model['animation_count']==0 and model['morph_target_count']==0
    assert model['editing']['semantic_regions']==[]
    assert model['editing']['source_morphs']==[]
    assert model['readiness']['morphs']=='absent'


def test_identical_bytes_are_idempotent_and_persist_across_metadata_reads(tmp_path):
    first = glb_file(tmp_path)
    second = tmp_path / 'renamed.glb'
    second.write_bytes(first.read_bytes())
    initial = model_library.register_model(first)
    repeated = model_library.register_model(second)
    assert initial == repeated
    assert model_library.list_models() == [initial]
    assert model_library.get_model(initial['id']) == initial
    updated = model_library.register_model(second, name='Renamed', source_credit='Confirmed source name')
    assert updated['id'] == initial['id']
    assert updated['name'] == 'Renamed'
    assert len(model_library.list_models()) == 1
    assert not list(storage.root().glob('assets/.import-*'))


@pytest.mark.parametrize('uri', ['existing.png', '../escape.bin', 'https://example.org/texture.png', 'file:///etc/passwd'])
def test_external_resource_uris_are_rejected_even_when_relative_file_exists(tmp_path, uri):
    (tmp_path / 'existing.png').write_bytes(b'not a model resource')
    source = glb_file(tmp_path, lambda doc: doc.update(images=[{'uri': uri}]))
    with pytest.raises(ValueError, match='external resource URIs'):
        model_library.register_model(source)
    assert model_library.list_models() == []
    assert not list(storage.root().glob('assets/*.glb'))


def test_external_uri_in_extension_is_rejected(tmp_path):
    source = glb_file(tmp_path, lambda doc: doc.update(extensions={'CUSTOM_resource': {'uri': 'elsewhere.bin'}}))
    with pytest.raises(ValueError, match='external resource URIs'):
        model_library.register_model(source)


@pytest.mark.parametrize('mutation, error', [
    (lambda doc: doc['accessors'][0].update(count=10_000), 'Accessor exceeds'),
    (lambda doc: doc['bufferViews'][0].update(byteOffset=10_000), 'Buffer view exceeds'),
    (lambda doc: doc['meshes'][0]['primitives'][0]['attributes'].update(POSITION=10_000), 'out-of-range'),
    (lambda doc: doc.update(meshes=[], nodes=[], skins=[], animations=[], scenes=[]), 'out-of-range|no meshes'),
])
def test_broken_geometry_is_rejected_without_registering(tmp_path, mutation, error):
    source = glb_file(tmp_path, mutation)
    with pytest.raises(ValueError, match=error):
        model_library.register_model(source)
    assert model_library.list_models() == []


def test_corrupt_header_and_oversize_inputs_are_rejected_and_temp_files_removed(tmp_path, monkeypatch):
    source = tmp_path / 'invalid.glb'
    source.write_bytes(b'not a GLB')
    with pytest.raises(ValueError, match='header'):
        model_library.register_model(source)
    source = glb_file(tmp_path)
    monkeypatch.setattr(model_library, 'MAX_MODEL_BYTES', 16)
    with pytest.raises(ValueError, match='150 MiB'):
        model_library.register_model(source)
    assert not list(storage.root().glob('assets/.import-*'))


def test_existing_different_bytes_are_never_overwritten(tmp_path):
    source = glb_file(tmp_path)
    result = model_library.register_model(source)
    destination = storage.asset_path(result['id'])
    destination.write_bytes(b'corrupted bytes')
    with pytest.raises(ValueError, match='differ from their recorded SHA-256'):
        model_library.register_model(source)
    assert destination.read_bytes() == b'corrupted bytes'


def test_model_endpoints_are_private_and_expose_metadata_without_local_paths(tmp_path, monkeypatch):
    source = glb_file(tmp_path)
    result = model_library.register_model(source)
    with TestClient(app) as client:
        response = client.get('/api/studio/models')
        assert response.status_code == 200 and response.json() == [result]
        assert str(tmp_path) not in response.text
        assert 'private-workspace' not in response.text
        assert client.get('/api/studio/models/' + result['id']).json() == result
        report = client.get('/api/studio/models/' + result['id'] + '/capabilities')
        assert report.status_code == 200
        assert report.json()['editing']['semantic_regions'] == []
        assert report.json()['editing']['source_morphs'][0]['mapping_status'] == 'unmapped'
        assert client.get('/api/studio/models/not-an-id').status_code == 404
        assert client.get(result['asset_url']).content == source.read_bytes()
        assert client.post('/api/studio/models', json={'path': str(source)}).status_code == 405
        monkeypatch.setenv('CHARACTER3D_STUDIO_TOKEN', 'private-test-token')
        assert client.get('/api/studio/models').status_code == 401
        assert client.get('/api/studio/models/' + result['id'] + '/capabilities').status_code == 401
        assert client.get(result['asset_url']).status_code == 401
        assert client.get('/api/studio/models', headers={'Authorization': 'Bearer private-test-token'}).status_code == 200
