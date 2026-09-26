from __future__ import annotations

from enum import Enum
import numpy as np
from pydantic import BaseModel, Field, model_validator


class BodyMorphAxis(str, Enum):
    X = "x"
    Y = "y"
    Z = "z"


class BodyProportionSlider(str, Enum):
    """General body-build/proportion controls (docs/ARCHITECTURE.md section 5's
    BODY SYSTEM list). Deliberately scoped to proportion/build only — the kind
    of slider present in any mainstream character creator (height, limb length,
    muscularity, ...) — not anatomical/sexual feature controls, which this
    project does not implement (see docs/SECURITY_AND_TRUST.md)."""

    HEIGHT = "height"
    SHOULDER_WIDTH = "shoulder_width"
    CHEST_DEPTH = "chest_depth"
    BUST_SIZE = "bust_size"
    TORSO_LENGTH = "torso_length"
    WAIST = "waist"
    HIP_WIDTH = "hip_width"
    GLUTE_SIZE = "glute_size"
    ARM_LENGTH = "arm_length"
    ARM_THICKNESS = "arm_thickness"
    LEG_LENGTH = "leg_length"
    LEG_THICKNESS = "leg_thickness"
    HAND_SIZE = "hand_size"
    FOOT_SIZE = "foot_size"
    NECK_THICKNESS = "neck_thickness"
    HEAD_SIZE = "head_size"
    MUSCULARITY = "muscularity"
    BODY_FAT = "body_fat"


class BodyMorphSpec(BaseModel):
    # Each slider is normalized to [-1, 1]: 0 = neutral/average, -1/+1 = the
    # region's minimum/maximum supported multiplier (see RegionAxisScale).
    sliders: dict[BodyProportionSlider, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_ranges(self):
        for slider, value in self.sliders.items():
            if not (-1.0 <= value <= 1.0):
                raise ValueError(f"slider {slider.value!r} out of range [-1, 1]: {value}")
        return self

    @property
    def extreme_slider_count(self) -> int:
        return sum(1 for v in self.sliders.values() if abs(v) >= 0.85)

    @classmethod
    def from_percentages(cls, percentages: dict[BodyProportionSlider | str, float]) -> "BodyMorphSpec":
        """Convenience constructor: percentages in [-100, 100] (0 = neutral,
        +100 = the region's maximum supported multiplier, -100 = its
        minimum) instead of raw [-1, 1] sliders. -100..100 is a more
        immediately intuitive scale for a caller building a UI or a quick
        script than "what does 0.4 even mean" -- it's exactly the same
        underlying value, just presented the way most mainstream character
        creators present their own sliders.
        """
        sliders: dict[BodyProportionSlider, float] = {}
        for key, pct in percentages.items():
            slider = key if isinstance(key, BodyProportionSlider) else BodyProportionSlider(key)
            sliders[slider] = pct / 100.0
        return cls(sliders=sliders)


class RegionAxisScale(BaseModel):
    """One named vertex-group region, scaled along one local axis about a
    pivot point. A slider typically drives more than one of these (e.g.
    SHOULDER_WIDTH might widen the shoulder region on X about the spine)."""

    region: str
    axis: BodyMorphAxis
    pivot: tuple[float, float, float] = (0.0, 0.0, 0.0)
    # Multiplier applied at slider value = +1.0. -1.0 applies the symmetric
    # inverse (1 / max_scale_multiplier), computed in log-space so +1 and -1
    # are equally spaced multiplicatively around a neutral 1.0 at value=0.
    max_scale_multiplier: float = Field(default=1.3, gt=1.0)


# Default region/axis mapping. Callers may override with their own rig's
# vertex-group names via apply_body_morphs(region_scales=...).
DEFAULT_SLIDER_REGIONS: dict[BodyProportionSlider, list[RegionAxisScale]] = {
    BodyProportionSlider.HEIGHT: [RegionAxisScale(region="whole_body", axis=BodyMorphAxis.Z, max_scale_multiplier=1.15)],
    BodyProportionSlider.SHOULDER_WIDTH: [RegionAxisScale(region="shoulders", axis=BodyMorphAxis.X, max_scale_multiplier=1.25)],
    BodyProportionSlider.CHEST_DEPTH: [RegionAxisScale(region="chest", axis=BodyMorphAxis.Y, max_scale_multiplier=1.2)],
    # General bust-size proportion control (a standard body-shape slider present
    # in mainstream, general-audience character creators), scaled outward on Y
    # about the chest/spine pivot -- a size/volume proportion, not an
    # anatomical-detail feature.
    BodyProportionSlider.BUST_SIZE: [RegionAxisScale(region="bust", axis=BodyMorphAxis.Y, max_scale_multiplier=1.4)],
    BodyProportionSlider.TORSO_LENGTH: [RegionAxisScale(region="torso", axis=BodyMorphAxis.Z, max_scale_multiplier=1.15)],
    BodyProportionSlider.WAIST: [RegionAxisScale(region="waist", axis=BodyMorphAxis.X, max_scale_multiplier=1.3)],
    BodyProportionSlider.HIP_WIDTH: [RegionAxisScale(region="hips", axis=BodyMorphAxis.X, max_scale_multiplier=1.25)],
    # General glute/buttock proportion control (same category as HIP_WIDTH and
    # BUST_SIZE: a standard body-shape slider in mainstream character
    # creators), scaled outward on Y about the hip/pelvis pivot.
    BodyProportionSlider.GLUTE_SIZE: [RegionAxisScale(region="glutes", axis=BodyMorphAxis.Y, max_scale_multiplier=1.35)],
    BodyProportionSlider.ARM_LENGTH: [RegionAxisScale(region="arms", axis=BodyMorphAxis.Z, max_scale_multiplier=1.2)],
    BodyProportionSlider.ARM_THICKNESS: [RegionAxisScale(region="arms", axis=BodyMorphAxis.X, max_scale_multiplier=1.3)],
    BodyProportionSlider.LEG_LENGTH: [RegionAxisScale(region="legs", axis=BodyMorphAxis.Z, max_scale_multiplier=1.2)],
    BodyProportionSlider.LEG_THICKNESS: [RegionAxisScale(region="legs", axis=BodyMorphAxis.X, max_scale_multiplier=1.3)],
    BodyProportionSlider.HAND_SIZE: [RegionAxisScale(region="hands", axis=BodyMorphAxis.X, max_scale_multiplier=1.3)],
    BodyProportionSlider.FOOT_SIZE: [RegionAxisScale(region="feet", axis=BodyMorphAxis.Z, max_scale_multiplier=1.3)],
    BodyProportionSlider.NECK_THICKNESS: [RegionAxisScale(region="neck", axis=BodyMorphAxis.X, max_scale_multiplier=1.25)],
    BodyProportionSlider.HEAD_SIZE: [RegionAxisScale(region="head", axis=BodyMorphAxis.X, max_scale_multiplier=1.15),
                                      RegionAxisScale(region="head", axis=BodyMorphAxis.Z, max_scale_multiplier=1.15)],
    BodyProportionSlider.MUSCULARITY: [RegionAxisScale(region="arms", axis=BodyMorphAxis.X, max_scale_multiplier=1.2),
                                        RegionAxisScale(region="torso", axis=BodyMorphAxis.Y, max_scale_multiplier=1.15)],
    BodyProportionSlider.BODY_FAT: [RegionAxisScale(region="torso", axis=BodyMorphAxis.X, max_scale_multiplier=1.25),
                                     RegionAxisScale(region="torso", axis=BodyMorphAxis.Y, max_scale_multiplier=1.25)],
}


def weights_from_indices(indices, n_vertices: int):
    """Convenience: turn a hard vertex-index list into a binary weight map,
    for simple fixtures/tests. Production regions should instead supply a
    continuous per-vertex weight map (see apply_body_morphs) so adjacent
    regions blend smoothly instead of producing a visible seam at a hard
    membership boundary."""
    import numpy as np

    w = np.zeros(n_vertices, dtype=np.float64)
    w[np.asarray(indices, dtype=np.int64)] = 1.0
    return w
