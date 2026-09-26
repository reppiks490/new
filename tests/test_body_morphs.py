import numpy as np
import pytest
import trimesh

from app.core.body_morphs import BodyMorphSpec, BodyProportionSlider, weights_from_indices
from app.rigging.body_morph_apply import apply_body_morphs


def _tall_box():
    # A tall box so "top half" / "bottom half" regions are unambiguous.
    return trimesh.creation.box(extents=(2.0, 2.0, 10.0))


def test_spec_rejects_out_of_range_slider():
    with pytest.raises(ValueError):
        BodyMorphSpec(sliders={BodyProportionSlider.HEIGHT: 1.5})


def test_bust_size_is_a_valid_slider_and_not_excluded():
    spec = BodyMorphSpec(sliders={BodyProportionSlider.BUST_SIZE: 0.6})
    assert spec.sliders[BodyProportionSlider.BUST_SIZE] == 0.6


def test_zero_value_slider_is_a_no_op():
    mesh = _tall_box()
    weights = weights_from_indices(np.arange(len(mesh.vertices)), len(mesh.vertices))
    spec = BodyMorphSpec(sliders={BodyProportionSlider.HEIGHT: 0.0})
    out = apply_body_morphs(mesh, spec, {"whole_body": weights})
    assert np.allclose(out.vertices, mesh.vertices)


def test_height_slider_scales_whole_body_region_about_pivot():
    mesh = _tall_box()
    weights = weights_from_indices(np.arange(len(mesh.vertices)), len(mesh.vertices))
    spec = BodyMorphSpec(sliders={BodyProportionSlider.HEIGHT: 1.0})
    out = apply_body_morphs(mesh, spec, {"whole_body": weights})
    # Height slider scales Z about pivot (0,0,0); a taller box has a larger Z extent.
    assert out.vertices[:, 2].max() > mesh.vertices[:, 2].max()
    assert out.bounds[1][2] - out.bounds[0][2] > mesh.bounds[1][2] - mesh.bounds[0][2]
    # Non-Z axes untouched by the height slider.
    assert np.allclose(out.vertices[:, 0], mesh.vertices[:, 0])
    assert np.allclose(out.vertices[:, 1], mesh.vertices[:, 1])


def test_continuous_weight_falloff_partially_affects_weighted_vertices():
    mesh = _tall_box()
    n = len(mesh.vertices)
    full = weights_from_indices(np.arange(n), n)
    half_weight = full * 0.5
    spec = BodyMorphSpec(sliders={BodyProportionSlider.HEIGHT: 1.0})

    out_full = apply_body_morphs(mesh, spec, {"whole_body": full})
    out_half = apply_body_morphs(mesh, spec, {"whole_body": half_weight})

    full_extent = out_full.bounds[1][2] - out_full.bounds[0][2]
    half_extent = out_half.bounds[1][2] - out_half.bounds[0][2]
    base_extent = mesh.bounds[1][2] - mesh.bounds[0][2]
    # Half weight should land strictly between no-change and full-strength change.
    assert base_extent < half_extent < full_extent


def test_unweighted_region_name_is_simply_ignored():
    mesh = _tall_box()
    spec = BodyMorphSpec(sliders={BodyProportionSlider.HEIGHT: 1.0})
    out = apply_body_morphs(mesh, spec, {})  # no regions supplied at all
    assert np.allclose(out.vertices, mesh.vertices)


def test_mismatched_weight_length_raises():
    mesh = _tall_box()
    spec = BodyMorphSpec(sliders={BodyProportionSlider.HEIGHT: 1.0})
    with pytest.raises(ValueError):
        apply_body_morphs(mesh, spec, {"whole_body": np.ones(3)})


def test_topology_is_preserved_only_vertex_positions_change():
    mesh = _tall_box()
    weights = weights_from_indices(np.arange(len(mesh.vertices)), len(mesh.vertices))
    spec = BodyMorphSpec(sliders={BodyProportionSlider.BUST_SIZE: 0.5})
    out = apply_body_morphs(mesh, spec, {"bust": weights})
    assert np.array_equal(out.faces, mesh.faces)
    assert len(out.vertices) == len(mesh.vertices)


def test_extreme_slider_count_tracks_near_limit_values():
    spec = BodyMorphSpec(sliders={
        BodyProportionSlider.HEIGHT: 0.9,
        BodyProportionSlider.WAIST: -0.9,
        BodyProportionSlider.HIP_WIDTH: 0.2,
    })
    assert spec.extreme_slider_count == 2
