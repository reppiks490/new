import numpy as np
import pytest

from app.world.biomes import classify_biomes
from app.world.terrain import TerrainSpec, diamond_square_heightmap
from app.world.terrain_selection import (
    BestOfNResult,
    TerrainCandidateScore,
    biome_diversity_score,
    height_range_utilization,
    score_heightmap,
    select_best_terrain_seed,
    walkable_area_ratio,
)


def _spec(**overrides):
    base = dict(name="t", size_meters=100.0, resolution_power=5, height_scale_meters=20.0, roughness=0.6)
    base.update(overrides)
    return TerrainSpec(**base)


def test_biome_diversity_is_zero_for_single_biome():
    flat = np.full((17, 17), 0.5)  # all PLAINS, no slope
    labels = classify_biomes(flat)
    assert biome_diversity_score(labels) == pytest.approx(0.0)


def test_biome_diversity_is_higher_for_varied_terrain():
    heightmap = diamond_square_heightmap(_spec(seed=1))
    labels = classify_biomes(heightmap)
    assert biome_diversity_score(labels) > 0.0


def test_biome_diversity_rejects_empty_input():
    with pytest.raises(ValueError):
        biome_diversity_score(np.zeros((0,)))


def test_walkable_area_ratio_is_full_for_flat_dry_land():
    flat = np.full((17, 17), 0.5)  # above water_level, zero slope
    assert walkable_area_ratio(flat) == pytest.approx(1.0)


def test_walkable_area_ratio_is_zero_when_fully_underwater():
    flat = np.full((17, 17), 0.0)  # below water_level everywhere
    assert walkable_area_ratio(flat) == pytest.approx(0.0)


def test_height_range_utilization_is_zero_for_flat_heightmap():
    flat = np.full((17, 17), 0.5)
    assert height_range_utilization(flat) == pytest.approx(0.0)


def test_height_range_utilization_is_higher_for_varied_terrain():
    heightmap = diamond_square_heightmap(_spec(seed=1))
    assert height_range_utilization(heightmap) > 0.0


def test_height_range_utilization_capped_at_one():
    # Bimodal extreme (half 0, half 1) has higher std than the uniform
    # reference distribution -- must still be clamped to 1.0, not exceed it.
    extreme = np.zeros((10, 10))
    extreme[:5] = 1.0
    assert height_range_utilization(extreme) == pytest.approx(1.0)


def test_score_heightmap_composite_is_weighted_sum_of_components():
    heightmap = diamond_square_heightmap(_spec(seed=1))
    score = score_heightmap(heightmap, seed=1, weights=(0.4, 0.35, 0.25))
    expected = (
        0.4 * score.biome_diversity + 0.35 * score.walkable_ratio + 0.25 * score.height_utilization
    )
    assert score.composite == pytest.approx(expected)


def test_select_best_terrain_seed_returns_all_candidate_scores():
    result = select_best_terrain_seed(_spec(), candidate_seeds=[1, 2, 3])
    assert isinstance(result, BestOfNResult)
    assert len(result.all_scores) == 3
    assert {s.seed for s in result.all_scores} == {1, 2, 3}


def test_select_best_terrain_seed_picks_the_actual_max_composite():
    result = select_best_terrain_seed(_spec(), candidate_seeds=[1, 2, 3, 4, 5])
    assert result.best_score.composite == max(s.composite for s in result.all_scores)
    assert result.best_seed == result.best_score.seed


def test_select_best_terrain_seed_is_deterministic():
    r1 = select_best_terrain_seed(_spec(), candidate_seeds=[1, 2, 3])
    r2 = select_best_terrain_seed(_spec(), candidate_seeds=[1, 2, 3])
    assert r1.best_seed == r2.best_seed
    assert r1.best_score.composite == pytest.approx(r2.best_score.composite)


def test_select_best_terrain_seed_rejects_empty_candidates():
    with pytest.raises(ValueError):
        select_best_terrain_seed(_spec(), candidate_seeds=[])


def test_select_best_terrain_seed_rejects_duplicate_seeds():
    with pytest.raises(ValueError):
        select_best_terrain_seed(_spec(), candidate_seeds=[1, 1, 2])


def test_degenerate_flat_terrain_scores_lower_than_real_varied_terrain():
    real = diamond_square_heightmap(_spec(seed=1))
    real_score = score_heightmap(real, seed=1)
    flat_score = score_heightmap(np.full(real.shape, 0.5), seed=999)
    assert flat_score.composite < real_score.composite
