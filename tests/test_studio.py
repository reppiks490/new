import hashlib
import io
import json
import numpy as np
from PIL import Image
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.studio.character import build_character
from app.studio.parameters import CharacterState, human_data
from app.studio.wardrobe import catalog, garment_mask
from app.studio.server import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('CHARACTER3D_STUDIO_WORKSPACE', str(tmp_path))
    monkeypatch.delenv('CHARACTER3D_STUDIO_TOKEN', raising=False)
    with TestClient(app) as c:
        yield c


def test_authored_targets_change_visible_body_and_restore_neutral():
    data = human_data()
    used = set(data['indices']) | set(data['eyes']['l']) | set(data['eyes']['r'])
    assert len(data['controls']) >= 240
    assert len({c['id'] for c in data['controls']}) == len(data['controls'])
    for c in data['controls']:
        for side in ('positive','negative'):
            assert any(v[0] in used and any(abs(d)>1e-8 for d in v[1:]) for v in c[side]), (c['id'], side)
    neutral = build_character(CharacterState()).geometry['body'].vertices.copy()
    altered = build_character(CharacterState(controls={'nose-scale-horiz':100})).geometry['body'].vertices
    assert not np.array_equal(neutral, altered)
    restored = build_character(CharacterState(controls={'nose-scale-horiz':0})).geometry['body'].vertices
    assert np.array_equal(neutral, restored)


@pytest.mark.parametrize('values', [{'unknown':1}, {'nose-scale-horiz':float('nan')},
                                  {'nose-scale-horiz':101}, {'nose-scale-horiz':float('inf')}])
def test_invalid_controls_are_rejected(values):
    with pytest.raises(ValidationError):
        CharacterState(controls=values)


def test_extended_range_is_explicit_and_bounded():
    assert CharacterState(extreme=True, controls={'nose-scale-horiz':150})
    with pytest.raises(ValidationError):
        CharacterState(extreme=True, controls={'nose-scale-horiz':151})


def test_every_wardrobe_recipe_has_distinct_nonempty_geometry():
    mesh = build_character(CharacterState()).geometry['body']
    masks = []
    for item in catalog():
        mask = garment_mask(mesh.triangles_center, mesh.bounds, item)
        assert mask.sum()>10, item['id']
        masks.append(hashlib.sha256(mask.tobytes()).hexdigest())
    assert len(catalog()) == 360
    assert len(set(masks)) == 360


def test_export_is_real_readable_glb_and_download_is_confined(client):
    import trimesh
    result = client.post('/api/studio/characters/export', json={}).json()
    response = client.get(result['url'])
    assert response.status_code == 200
    scene = trimesh.load(io.BytesIO(response.content), file_type='glb', force='scene')
    assert 'body' in scene.geometry and 'garment' in scene.geometry
    assert len(scene.geometry['body'].faces) == 26756
    assert client.get('/api/studio/assets/not-an-id.glb').status_code == 404
    assert client.get('/api/studio/assets/'+'a'*32+'.txt').status_code == 404
    assert client.post('/api/studio/characters/export', json={'outfit':'missing'}).status_code == 422


def test_project_reload_preserves_settings(client):
    payload = {'name':'Example','character':{'skin':'#123456','controls':{'nose-scale-horiz':35}}}
    saved = client.post('/api/studio/projects', json=payload)
    assert saved.status_code == 200
    reloaded = client.get('/api/studio/projects/'+saved.json()['id']).json()
    assert reloaded['character']['controls'] == payload['character']['controls']
    assert reloaded['character']['skin'] == '#123456'
    assert client.post('/api/studio/projects', json={**payload,'schema_version':2}).status_code == 422


def test_waist_edit_is_saved_and_exported_as_geometry(client):
    edit={'region':'waist','operation':'reduce_width','amount_pct':8,
          'protected_regions':['hips','glutes']}
    payload={'name':'Constrained waist edit','character':{'body_edits':[edit]}}
    saved=client.post('/api/studio/projects',json=payload)
    assert saved.status_code==200
    loaded=client.get('/api/studio/projects/'+saved.json()['id'])
    assert loaded.json()['character']['body_edits']==[edit]
    exported=client.post('/api/studio/characters/export',json={'body_edits':[edit]})
    assert exported.status_code==200
    import trimesh
    mesh=trimesh.load(io.BytesIO(client.get(exported.json()['url']).content),file_type='glb',force='scene').geometry['body']
    original=np.asarray(human_data()['positions'])
    assert not np.array_equal(mesh.vertices,original)


def test_private_api_requires_token_and_rejects_untrusted_origins(client, monkeypatch):
    monkeypatch.setenv('CHARACTER3D_STUDIO_TOKEN','test-secret')
    assert client.get('/api/studio/capabilities').status_code == 401
    headers={'Authorization':'Bearer test-secret'}
    response = client.get('/api/studio/capabilities', headers=headers)
    assert response.status_code == 200 and 'test-secret' not in response.text
    assert response.json()['body_editing']['supported_base_regions'] == ['breasts', 'glutes', 'hips', 'waist']
    assert response.json()['body_editing']['protected_regions'] == ['breasts', 'glutes', 'hips', 'waist']
    assert response.json()['body_editing']['percentage_semantics'].startswith('authored_target_strength')
    assert client.post('/api/studio/projects', json={'name':'test','character':{}},
                       headers={**headers,'Origin':'https://untrusted.example'}).status_code == 403
    assert client.get('/').status_code == 200


def test_images_are_decoded_and_reencoded_with_metadata_removed(client):
    assert client.post('/api/studio/images', files={'file':('bad.png',b'broken','image/png')}).status_code == 422
    buf=io.BytesIO();Image.new('RGB',(20,20),'blue').save(buf,format='PNG')
    response=client.post('/api/studio/images', files={'file':('good.png',buf.getvalue(),'image/png')})
    assert response.status_code == 200
    downloaded=client.get(response.json()['url'])
    image=Image.open(io.BytesIO(downloaded.content))
    assert image.size == (20,20) and image.format == 'PNG'


def test_generation_without_credentials_does_not_create_fake_result(client,monkeypatch):
    for name in ['TRIPO_API_KEY','MESHY_API_KEY','HI3D_API_KEY']:
        monkeypatch.delenv(name,raising=False)
    assert client.post('/api/studio/generate', json={'kind':'text','provider':'tripo','prompt':'A ceramic vase'}).status_code == 503
    assert client.get('/api/studio/jobs').json() == []
    assert client.post('/api/studio/generate', json={'kind':'image','provider':'hi3d','image_id':'../secret'}).status_code == 422
