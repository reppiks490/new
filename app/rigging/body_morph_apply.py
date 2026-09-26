from __future__ import annotations

import numpy as np
import trimesh

from app.core.body_morphs import BodyMorphSpec, BodyProportionSlider, DEFAULT_SLIDER_REGIONS, RegionAxisScale
from app.rigging.auto_region_weights import UNSUPPORTED_REGIONS, estimate_default_region_weights

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


def apply_body_morphs_auto(
    mesh: trimesh.Trimesh,
    spec: BodyMorphSpec,
    region_weights: dict[str, np.ndarray] | None = None,
    *,
    region_scales: dict[BodyProportionSlider, list[RegionAxisScale]] | None = None,
) -> trimesh.Trimesh:
    """Convenience wrapper: any region NOT explicitly supplied in
    region_weights is auto-estimated from the mesh's own bounding box
    (app.rigging.auto_region_weights.estimate_default_region_weights),
    so a caller can use the 11 auto-supported sliders (everything except
    "arms"/"hands" -- see UNSUPPORTED_REGIONS) with zero manual setup, and
    only needs to hand-author region_weights for the regions that actually
    need it. Caller-supplied entries always take precedence over the
    auto-estimated ones for the same region name.
    """
    region_weights = dict(region_weights or {})
    needed_regions = {
        rs.region
        for slider, value in spec.sliders.items()
        if value != 0
        for rs in (region_scales or DEFAULT_SLIDER_REGIONS).get(slider, [])
    }
    missing = needed_regions - region_weights.keys()
    if missing:
        auto = estimate_default_region_weights(mesh.vertices)
        for region in missing:
            if region in auto:
                region_weights[region] = auto[region]
            elif region in UNSUPPORTED_REGIONS:
                raise ValueError(
                    f"region {region!r} has no supplied weights and is not auto-estimated "
                    f"(see app.rigging.auto_region_weights.UNSUPPORTED_REGIONS); "
                    "supply region_weights for it explicitly."
                )
            # A region name outside both auto-support and the caller's own
            # weights simply gets skipped by apply_body_morphs itself
            # (weights.get(rs.region) is None -> that RegionAxisScale is a
            # no-op), matching its existing behavior for unknown regions.
    return apply_body_morphs(mesh, spec, region_weights, region_scales=region_scales)
