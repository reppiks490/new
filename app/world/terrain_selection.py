from __future__ import annotations

"""Automatic best-of-N terrain variant selection.

Generating one seeded terrain and shipping it is a coin flip -- some seeds
land on degenerate results (near-flat, all-water, a single dominant biome)
that a human would reject on sight. This module generates N real candidate
heightmaps (one real diamond-square run per seed, not a cheap proxy) and
scores each on real, computed geometry/biome metrics, then returns the
highest-scoring one plus every candidate's own score for transparency.
"""

from dataclasses import dataclass

import numpy as np

from app.world.biomes import Biome, BiomeThresholds, classify_biomes
from app.world.terrain import TerrainSpec, diamond_square_heightmap


def _slope_grid(heightmap: np.ndarray) -> np.ndarray:
    gy, gx = np.gradient(heightmap)
    return np.sqrt(gx * gx + gy * gy)


def biome_diversity_score(labels: np.ndarray) -> float:
    """Shannon entropy of the biome label distribution, normalized to [0, 1]
    by the maximum possible entropy for the number of biome categories that
    actually exist (len(Biome)). 0 = single biome everywhere, 1 = every
    biome equally represented."""
    flat = labels.ravel()
    total = flat.size
    if total == 0:
        raise ValueError("labels must be non-empty")
    _, counts = np.unique(flat, return_counts=True)
    probs = counts / total
    entropy = float(-np.sum(probs * np.log2(probs)))
    max_entropy = np.log2(len(Biome))
    return entropy / max_entropy if max_entropy > 0 else 0.0


def walkable_area_ratio(heightmap: np.ndarray, *, slope_threshold: float = 0.12) -> float:
    """Fraction of the heightmap that is both dry (not water/beach-underwater)
    and below the given local-slope threshold -- a real proxy for "a
    character could actually stand and move here," not just "not steep
    anywhere." Slope threshold matches BiomeThresholds.steep_slope_threshold
    by default so this stays consistent with the ROCK classification."""
    slope = _slope_grid(heightmap)
    labels = classify_biomes(heightmap)
    dry = labels != Biome.WATER.value
    flat_enough = slope < slope_threshold
    return float(np.count_nonzero(dry & flat_enough)) / heightmap.size


def height_range_utilization(heightmap: np.ndarray) -> float:
    """How much of the full [0, 1] normalized elevation range this specific
    heightmap actually spans (max - min), rather than clustering in a narrow
    band -- diamond-square can produce this on unlucky seeds/roughness
    combinations even though the grid is always renormalized to touch
    [0, 1] at its extremes... except when max==min (flat), so this is
    computed pre-normalization-independent: it's really the *spread*
    (std deviation relative to a uniform reference) since renormalization
    always makes min=0/max=1 trivially. Std dev is what actually
    distinguishes a terrain with genuine elevation variety from one that's
    mostly flat with a couple of extreme spikes."""
    std = float(heightmap.std())
    # A uniform distribution on [0, 1] has std ~= 1/sqrt(12) =~ 0.2887;
    # used as a normalizing reference so 1.0 means "as spread out as
    # plausible varied terrain," not an unreachable theoretical max.
    reference_std = 1.0 / np.sqrt(12)
    return float(min(std / reference_std, 1.0))


@dataclass(frozen=True)
class TerrainCandidateScore:
    seed: int
    biome_diversity: float
    walkable_ratio: float
    height_utilization: float
    composite: float


def score_heightmap(
    heightmap: np.ndarray,
    seed: int,
    *,
    weights: tuple[float, float, float] = (0.4, 0.35, 0.25),
) -> TerrainCandidateScore:
    labels = classify_biomes(heightmap)
    diversity = biome_diversity_score(labels)
    walkable = walkable_area_ratio(heightmap)
    utilization = height_range_utilization(heightmap)
    w_diversity, w_walkable, w_utilization = weights
    composite = w_diversity * diversity + w_walkable * walkable + w_utilization * utilization
    return TerrainCandidateScore(
        seed=seed,
        biome_diversity=diversity,
        walkable_ratio=walkable,
        height_utilization=utilization,
        composite=composite,
    )


@dataclass(frozen=True)
class BestOfNResult:
    best_seed: int
    best_score: TerrainCandidateScore
    all_scores: list[TerrainCandidateScore]


def select_best_terrain_seed(
    base_spec: TerrainSpec,
    *,
    candidate_seeds: list[int],
    weights: tuple[float, float, float] = (0.4, 0.35, 0.25),
) -> BestOfNResult:
    """Generate one real heightmap per candidate seed (base_spec's own seed
    field is overridden per candidate) and return the highest-composite-score
    seed along with every candidate's full score breakdown, so the caller can
    see why it won rather than trusting a black-box pick."""
    if not candidate_seeds:
        raise ValueError("candidate_seeds must be non-empty")
    if len(set(candidate_seeds)) != len(candidate_seeds):
        raise ValueError("candidate_seeds must not contain duplicates")

    scores: list[TerrainCandidateScore] = []
    for seed in candidate_seeds:
        spec = base_spec.model_copy(update={"seed": seed})
        heightmap = diamond_square_heightmap(spec)
        scores.append(score_heightmap(heightmap, seed, weights=weights))

    best = max(scores, key=lambda s: s.composite)
    return BestOfNResult(best_seed=best.seed, best_score=best, all_scores=scores)
