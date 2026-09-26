from __future__ import annotations

import numpy as np
import trimesh

from app.core.body_morphs import BodyMorphSpec, BodyProportionSlider, DEFAULT_SLIDER_REGIONS, RegionAxisScale

_AXIS_INDEX = {"x": 0, "y": 1, "z": 2}


def _slider_to_multiplier(value: float, max_multiplier: float) -> float:
    # value in [-1, 1] -> multiplicative scale, symmetric in log-space around
    # 1.0 at value=0: +1 -> max_multiplier, -1 -> 1/max_multiplier.
    return max_multiplier ** value


def apply_body_morphs(
    mesh: trimesh.Trimesh,
    spec: BodyMorphSpec,
    region_weights: dict[str, np.ndarray],
    *,
    region_scales: dict[BodyProportionSlider, list[RegionAxisScale]] | None = None,
) -> trimesh.Trimesh:
    """Apply proportion sliders as continuous, per-vertex-weighted regional
    scaling about a pivot -- not a hard vertex-group boundary and not a crude
    whole-mesh scale (docs/ARCHITECTURE.md explicitly warns against the
    latter: "Avoid crude global vertex scaling where it produces poor
    anatomy"). Each region_weights[name] is a float array, one weight per
    mesh vertex, typically smoothly falling off from 1.0 at the region's core
    to 0.0 at its boundary, so adjacent regions blend instead of seaming.

    Multiple sliders touching the same region+axis compose sequentially
    (each multiplier applied to the running vertex positions), so overlapping
    influence (e.g. MUSCULARITY and BODY_FAT both touching "torso") combines
    naturally rather than one silently overwriting the other.
    """
    region_scales = region_scales or DEFAULT_SLIDER_REGIONS
    n = len(mesh.vertices)
    for name, weights in region_weights.items():
        if len(weights) != n:
            raise ValueError(f"region_weights[{name!r}] has {len(weights)} entries, mesh has {n} vertices")
        if weights.min() < 0.0 or weights.max() > 1.0:
            raise ValueError(f"region_weights[{name!r}] must be within [0, 1]")

    vertices = mesh.vertices.copy()
    for slider, value in spec.sliders.items():
        if value == 0:
            continue
        for rs in region_scales.get(slider, []):
            weights = region_weights.get(rs.region)
            if weights is None:
                continue
            multiplier = _slider_to_multiplier(value, rs.max_scale_multiplier)
            # Blend neutral (1.0) -> multiplier by per-vertex weight, so a
            # vertex at the region's edge (weight ~0) is barely affected and
            # the region's core (weight ~1) gets the full multiplier.
            blended = 1.0 + (multiplier - 1.0) * weights
            ax = _AXIS_INDEX[rs.axis.value]
            pivot_component = rs.pivot[ax]
            vertices[:, ax] = pivot_component + (vertices[:, ax] - pivot_component) * blended

    return trimesh.Trimesh(vertices=vertices, faces=mesh.faces, process=False)
