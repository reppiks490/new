import numpy as np
import pytest

from app.rigging.auto_region_weights import UNSUPPORTED_REGIONS, _HEIGHT_BANDS, estimate_default_region_weights

_TOTAL_HEIGHT = 182.5
_PAD = np.array([[0, 0, -0.5], [0, 0, 182.0]])

# Dense, near-centerline point clouds at each region's own expected
# height-fraction center -- verified against this exact methodology before
# finalizing the module (coarse box/cylinder primitives gave misleading
# results because their vertices concentrate at corners/rings rather than
# being continuously distributed, which isn't representative of a real
# generated character mesh's vertex density).
_REGION_TEST_BANDS = {
    "feet": (0.02, 0.01), "legs": (0.28, 0.05), "hips": (0.47, 0.01),
    "glutes": (0.46, 0.01), "waist": (0.53, 0.01), "torso": (0.62, 0.02),
    "chest": (0.66, 0.01), "shoulders": (0.80, 0.005), "neck": (0.85, 0.005),
    "head": (0.93, 0.02),
}


def _dense_band(z_center_frac, jitter, n=500, seed=0):
    rng = np.random.default_rng(seed)
    z = rng.uniform(z_center_frac - jitter, z_center_frac + jitter, n) * _TOTAL_HEIGHT
    x = rng.uniform(-8, 8, n)
    y = rng.uniform(-8, 8, n)
    return np.vstack([np.stack([x, y, z], axis=1), _PAD])


@pytest.mark.parametrize("region", sorted(_REGION_TEST_BANDS))
def test_region_correctly_dominates_its_own_height_band(region):
    z_center, jitter = _REGION_TEST_BANDS[region]
    pts = _dense_band(z_center, jitter)
    weights = estimate_default_region_weights(pts)
    idx = slice(0, len(pts) - 2)
    means = {r: float(weights[r][idx].mean()) for r in _HEIGHT_BANDS}
    dominant = max(means, key=means.get)
    assert dominant == region, f"expected {region!r} to dominate, got {dominant!r} ({means})"


def test_bust_and_chest_are_deliberately_near_identical_not_a_bug():
    # bust_size and chest_depth are two different sliders acting on the
    # SAME anatomical area with different multipliers, so their auto-
    # estimated regions are intentionally nearly identical rather than
    # cleanly separated the way e.g. head vs. feet are.
    pts = _dense_band(0.66, 0.01)
    weights = estimate_default_region_weights(pts)
    idx = slice(0, len(pts) - 2)
    chest_mean = weights["chest"][idx].mean()
    bust_mean = weights["bust"][idx].mean()
    assert abs(chest_mean - bust_mean) < 0.05


def test_arms_and_hands_are_not_auto_estimated():
    assert UNSUPPORTED_REGIONS == frozenset({"arms", "hands"})
    pts = _dense_band(0.5, 0.3)
    weights = estimate_default_region_weights(pts)
    assert "arms" not in weights
    assert "hands" not in weights


def test_whole_body_is_always_full_weight():
    pts = _dense_band(0.5, 0.3)
    weights = estimate_default_region_weights(pts)
    assert (weights["whole_body"] == 1.0).all()


def test_rejects_non_nx3_input():
    with pytest.raises(ValueError):
        estimate_default_region_weights(np.zeros((10, 2)))


def test_rejects_zero_height_mesh():
    flat = np.zeros((10, 3))
    with pytest.raises(ValueError):
        estimate_default_region_weights(flat)


def test_rejects_empty_input():
    with pytest.raises(ValueError):
        estimate_default_region_weights(np.zeros((0, 3)))
