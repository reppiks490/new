import json
from pathlib import Path

import numpy as np

from app.studio.body_edits import apply_body_edits, build_region_masks
from app.studio.character import build_character
from app.studio.parameters import CharacterState


def data():
    return json.loads((Path(__file__).parents[1] / 'app/studio/web/data/human.json').read_text())


def test_waist_edit_changes_waist_while_protecting_authored_hip_and_glute_regions():
    source=data()
    vertices=np.asarray(source['positions'],dtype=float)
    masks=build_region_masks(vertices,source)
    assert len(masks['waist']) > 500
    assert len(masks['hips']) > 1000
    assert len(masks['glutes']) > 500
    assert not (masks['waist'] & masks['hips'])
    assert not (masks['waist'] & masks['glutes'])
    result,report=apply_body_edits(vertices,source,[{
        'region':'waist','operation':'reduce_width','amount_pct':10,
        'protected_regions':['hips','glutes']
    }])
    delta=np.linalg.norm(result-vertices,axis=1)
    assert np.all(delta[list(masks['hips'])] == 0)
    assert np.all(delta[list(masks['glutes'])] == 0)
    assert np.any(delta[list(masks['waist'])] > 0)
    assert report[0]['protected_max_delta']['hips']==0
    assert report[0]['protected_max_delta']['glutes']==0
    assert report[0]['changed_vertices'] > 500
    assert np.isfinite(result).all()


def test_waist_reduction_preserves_topology_and_positive_triangle_orientation():
    import trimesh
    source=data()
    vertices=np.asarray(source['positions'],dtype=float)
    faces=np.asarray(source['indices']).reshape(-1,3)
    changed,_=apply_body_edits(vertices,source,[{
        'region':'waist','operation':'reduce_width','amount_pct':15,
        'protected_regions':['hips','glutes']
    }])
    before=trimesh.Trimesh(vertices=vertices,faces=faces,process=False)
    after=trimesh.Trimesh(vertices=changed,faces=faces,process=False)
    assert np.array_equal(before.faces,after.faces)
    dots=np.einsum('ij,ij->i',before.face_normals,after.face_normals)
    assert np.all(dots > 0)


def test_unsupported_or_out_of_range_region_edits_are_rejected():
    source=data();vertices=np.asarray(source['positions'],dtype=float)
    for edit in [
        {'region':'hips','operation':'reduce_width','amount_pct':10,'protected_regions':[]},
        {'region':'waist','operation':'reduce_size','amount_pct':10,'protected_regions':[]},
        {'region':'waist','operation':'increase_width','amount_pct':1,'protected_regions':[]},
        {'region':'waist','operation':'reduce_width','amount_pct':16,'protected_regions':[]},
    ]:
        try:
            apply_body_edits(vertices,source,[edit])
        except ValueError:
            continue
        raise AssertionError(f'unsupported edit accepted: {edit}')
    repeated=[{'region':'waist','operation':'reduce_width','amount_pct':10,'protected_regions':[]}]*2
    try:
        apply_body_edits(vertices,source,repeated)
    except ValueError as error:
        assert 'Combined' in str(error)
    else:
        raise AssertionError('repeated waist edits exceeded the cumulative limit')


def test_character_export_mesh_and_fitted_garment_use_the_accepted_body_edit():
    data_value=data()
    neutral=build_character(CharacterState())
    edited=build_character(CharacterState(body_edits=[{
        'region':'waist','operation':'reduce_width','amount_pct':10,
        'protected_regions':['hips','glutes']
    }]))
    base=neutral.geometry['body'].vertices
    result=edited.geometry['body'].vertices
    masks=build_region_masks(base,data_value)
    delta=np.linalg.norm(result-base,axis=1)
    assert np.any(delta[list(masks['waist'])]>0)
    assert np.all(delta[list(masks['hips'])]==0)
    assert np.all(delta[list(masks['glutes'])]==0)
    assert edited.metadata['body_edit_reports'][0]['protected_max_delta']=={'hips':0.0,'glutes':0.0}


def test_body_edit_schema_rejects_unknown_controls_and_excessive_amounts():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        CharacterState(body_edits=[{'region':'hips','operation':'reduce_width','amount_pct':10}])
    with pytest.raises(ValidationError):
        CharacterState(body_edits=[{'region':'waist','operation':'reduce_width','amount_pct':16}])
    with pytest.raises(ValidationError):
        CharacterState(body_edits=[{'region':'waist','operation':'reduce_width','amount_pct':10,'unexpected':True}])
    with pytest.raises(ValidationError):
        CharacterState(body_edits=[{'region':'waist','operation':'reduce_width','amount_pct':True}])
    with pytest.raises(ValidationError):
        CharacterState(body_edits=[
            {'region':'waist','operation':'reduce_width','amount_pct':10},
            {'region':'waist','operation':'reduce_width','amount_pct':10},
        ])


def test_masculine_base_waist_mask_keeps_authored_hip_and_glute_vertices_fixed():
    import pytest
    source=data();vertices=np.asarray(source['positions'],dtype=float)
    for delta in source['bases']['male']:
        rows=np.asarray(delta);indices=rows[:,0].astype(int);vertices[indices]+=rows[:,1:]/3
    try:
        edited,report=apply_body_edits(vertices,source,[{
            'region':'waist','operation':'reduce_width','amount_pct':10,
            'protected_regions':['hips','glutes']
        }])
    except ValueError as error:
        pytest.fail(f'The supported masculine base must have a valid authored waist map: {error}')
    masks=build_region_masks(vertices,source);delta=np.linalg.norm(edited-vertices,axis=1)
    assert report[0]['changed_vertices']>500
    assert np.all(delta[list(masks['hips'])]==0)
    assert np.all(delta[list(masks['glutes'])]==0)
