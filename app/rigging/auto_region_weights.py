from __future__ import annotations

import numpy as np

# Height fraction (0 = lowest point, 1 = highest point) at the center of
# each named body region, and the half-width of its smooth falloff band.
# Based on common ~7.5-8-head-tall figure-drawing proportion conventions --
# a reasonable DEFAULT for a neutral-pose, roughly humanoid, Z-up mesh, not
# measured from any specific character. Real per-character topology
# varies; apply_body_morphs always accepts hand-authored region_weights for
# production precision -- this exists so a first pass works on any mesh
# with zero manual setup.
#
# Scope, established by testing against both coarse and densely-sampled
# synthetic geometry before finalizing (not assumed): height-band-only
# weighting works well for these 11 regions, which are all reasonably
# centered near the body's vertical axis regardless of pose. It was NOT
# extended to "arms"/"hands": a lateral-distance term was tried and
# rejected after testing against a simulated T-pose arm (horizontal, far
# lateral, shoulder height) and a simulated A-pose/rest arm (hanging,
# moderate lateral, spanning hip-to-shoulder height) -- in both cases
# competing torso-axis regions (shoulders, torso, chest) outscored "arms"
# at the same height, because arm position is fundamentally pose-dependent
# in a way a static height+lateral heuristic can't robustly resolve.
# Limb regions need either a known bind-pose skeleton or manually authored
# region_weights; this module does not pretend otherwise.
_HEIGHT_BANDS: dict[str, tuple[float, float]] = {
    "feet": (0.02, 0.05),
    "legs": (0.28, 0.24),
    "hips": (0.47, 0.06),
    "glutes": (0.46, 0.05),
    "waist": (0.53, 0.05),
    "torso": (0.62, 0.10),
    "chest": (0.66, 0.08),
    "bust": (0.66, 0.06),
    "shoulders": (0.80, 0.04),
    "neck": (0.85, 0.03),
    "head": (0.93, 0.08),
}

# Not auto-estimated -- see the scope note above. Listed explicitly (rather
# than just absent) so a caller checking "which regions does this NOT
# cover" doesn't have to diff against DEFAULT_SLIDER_REGIONS by hand.
UNSUPPORTED_REGIONS = frozenset({"arms", "hands"})


def _smooth_band(values: np.ndarray, center: float, half_width: float) -> np.ndarray:
    if half_width <= 0:
        raise ValueError("half_width must be positive")
    dist = np.abs(values - center) / half_width
    return np.clip(1.0 - dist, 0.0, 1.0)


def estimate_default_region_weights(vertices) -> dict[str, np.ndarray]:
    """Heuristic per-vertex weight maps for the 11 body regions listed in
    _HEIGHT_BANDS, derived purely from a mesh's own bounding box (Z=up,
    matching this project's convention throughout) -- no pre-authored
    vertex groups required to get a body-morph pipeline running for those
    regions. Smooth triangular-ramp height-band falloff (not a hard
    cutoff, consistent with apply_body_morphs' own "no crude boundaries"
    design).

    Does NOT cover "arms"/"hands" (see UNSUPPORTED_REGIONS and the module
    docstring above for why) -- callers needing those must supply their
    own region_weights entries for them.
    """
    v = np.asarray(vertices, dtype=np.float64)
    if v.ndim != 2 or v.shape[1] != 3:
        raise ValueError("vertices must be an (N, 3) array")
    if len(v) == 0:
        raise ValueError("vertices must be non-empty")

    z = v[:, 2]
    z_min, z_max = float(z.min()), float(z.max())
    height = z_max - z_min
    if height <= 0:
        raise ValueError("mesh has zero height (Z extent); cannot derive height-band weights")
    z_frac = (z - z_min) / height

    weights: dict[str, np.ndarray] = {"whole_body": np.ones(len(v), dtype=np.float64)}
    for region, (center, half_width) in _HEIGHT_BANDS.items():
        weights[region] = _smooth_band(z_frac, center, half_width)
    return weights
