"""Regional controls must visibly deform the correct area and preserve reset."""
import numpy as np
import pytest
from app.studio.character import build_character
from app.studio.parameters import CharacterState, human_data


def test_breast_and_glute_families_are_real_distinct_operations():
    controls={c['id']:c for c in human_data()['controls']}
    required={'breast-size','breast-dist','breast-trans-vertical','breast-firmness',
              'breast-projection','breast-width','breast-upper-fullness','breast-lower-fullness',
              'buttocks-volume','glute-projection','glute-width','glute-lift','glute-roundness',
              'glute-upper-fullness','glute-lower-fullness'}
    assert required <= controls.keys()
    fingerprints=set()
    for name in required:
        c=controls[name]
        d=np.array(c['positive'])
        assert np.isfinite(d).all() and np.linalg.norm(d[:,1:])>0.01
        fingerprints.add(tuple(map(tuple,d)))
    assert len(fingerprints)==len(required)


@pytest.mark.parametrize('region',['breast','glute'])
def test_independent_side_size_does_not_move_opposite_side(region):
    data=human_data();controls={c['id']:c for c in data['controls']}
    vertices=np.array(data['positions'])
    for prefix,sign in [('l',1),('r',-1)]:
        d=np.array(controls[f'{prefix}-{region}-size']['positive'])
        ids=d[:,0].astype(int)
        assert np.linalg.norm(d[:,1:])>0
        opposite=vertices[ids,0]*sign<0
        assert np.all(d[opposite,1:]==0)


@pytest.mark.parametrize('control',['breast-size','buttocks-volume'])
def test_size_changes_geometry_and_zero_restores_original(control):
    neutral=build_character(CharacterState()).geometry['body'].vertices
    changed=build_character(CharacterState(controls={control:100})).geometry['body'].vertices
    assert np.max(np.linalg.norm(changed-neutral,axis=1))>.01
    reset=build_character(CharacterState(controls={control:0})).geometry['body'].vertices
    assert np.array_equal(reset,neutral)


def test_extreme_curve_combination_keeps_finite_mesh_and_fitted_shell():
    controls={'breast-size':150,'breast-projection':100,'buttocks-volume':150,'glute-width':100}
    scene=build_character(CharacterState(extreme=True,controls=controls))
    body=scene.geometry['body'];garment=scene.geometry['garment']
    assert np.isfinite(body.vertices).all() and len(garment.faces)>100
    assert len(garment.vertices)==len(body.vertices)
    assert np.max(np.linalg.norm(garment.vertices-body.vertices,axis=1))<.004
