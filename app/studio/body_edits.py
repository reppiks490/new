"""Versioned, source-specific region masks and constrained local body edits."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

MASK_PATH = Path(__file__).parent / 'web/data/body_region_masks.json'


@lru_cache(maxsize=1)
def mask_spec() -> dict:
    return json.loads(MASK_PATH.read_text())


def _shape_support(data: dict, control_ids: list[str]) -> set[int]:
    controls = {item['id']: item for item in data['controls']}
    missing = set(control_ids) - controls.keys()
    if missing:
        raise ValueError('Region mask references missing authored controls: ' + ', '.join(sorted(missing)))
    return {
        int(row[0])
        for control_id in control_ids
        for side in ('positive', 'negative')
        for row in controls[control_id][side]
    }


def build_region_masks(vertices, data: dict) -> dict[str, set[int]]:
    """Build reproducible vertex masks from authored target support and bounds."""
    vertices = np.asarray(vertices, dtype=float)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not np.isfinite(vertices).all():
        raise ValueError('Body mesh vertices must be finite XYZ coordinates')
    spec = mask_spec()['regions']
    masks = {}
    for name, config in spec.items():
        if name == 'waist':
            continue
        masks[name] = _shape_support(data, config['authored_support_controls'])
    waist = spec['waist']
    candidate = _shape_support(data, [waist['candidate_support_control']])
    excluded = set().union(*(masks[name] for name in waist['exclude_regions']))
    lower, upper = waist['vertical_bounds']
    x_limit = waist['max_abs_x']
    masks['waist'] = {
        index for index in candidate - excluded
        if index < len(vertices) and lower < vertices[index, 1] < upper
        and abs(vertices[index, 0]) < x_limit
    }
    if not masks['waist']:
        raise ValueError('The authored waist mask is empty for this base mesh')
    return masks


def _smooth_weight(y: np.ndarray, lower: float, full_low: float, full_high: float, upper: float) -> np.ndarray:
    weight = np.zeros_like(y, dtype=float)
    rising = (y > lower) & (y < full_low)
    t = (y[rising] - lower) / (full_low - lower)
    weight[rising] = t * t * (3 - 2 * t)
    weight[(y >= full_low) & (y <= full_high)] = 1
    falling = (y > full_high) & (y < upper)
    t = (upper - y[falling]) / (upper - full_high)
    weight[falling] = t * t * (3 - 2 * t)
    return weight


def apply_body_edits(vertices, data: dict, edits: list[dict]) -> tuple[np.ndarray, list[dict]]:
    """Apply supported edits and return derived vertices with measured deltas.

    Current support is intentionally limited to the inspected CC0 base waist.
    Hip, glute, and breast vertices are excluded from the waist mask.
    """
    original = np.asarray(vertices, dtype=float)
    if original.ndim != 2 or original.shape[1] != 3 or not np.isfinite(original).all():
        raise ValueError('Body mesh vertices must be finite XYZ coordinates')
    if not isinstance(edits, list) or len(edits) > 10:
        raise ValueError('At most 10 body edit operations are supported')
    if sum(edit.get('amount_pct', 0) for edit in edits if isinstance(edit, dict)) > 15:
        raise ValueError('Combined waist width reduction cannot exceed 15 percent')
    result = original.copy()
    masks = build_region_masks(result, data)
    spec = mask_spec()['regions']['waist']
    reports = []
    for edit in edits:
        if not isinstance(edit, dict) or edit.get('region') != 'waist' or edit.get('operation') != 'reduce_width':
            raise ValueError('Only mapped waist width edits are supported on this base')
        amount = edit.get('amount_pct')
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not np.isfinite(amount) or amount <= 0 or amount > spec['max_amount_percent']:
            raise ValueError(f"Waist edit amount must be greater than 0 and at most {spec['max_amount_percent']} percent")
        protected = edit.get('protected_regions', [])
        if not isinstance(protected, list) or not set(protected) <= {'hips', 'glutes'}:
            raise ValueError('Waist edits can only protect mapped hips and glutes')
        mask = np.zeros(len(result), dtype=bool)
        indices = np.fromiter(masks['waist'], dtype=np.int64)
        mask[indices] = True
        lower, upper = spec['vertical_bounds']
        full_low, full_high = spec['full_influence_bounds']
        weight = _smooth_weight(result[:, 1], lower, full_low, full_high, upper)
        weight[~mask] = 0
        result[:, 0] -= result[:, 0] * (float(amount) / 100) * weight
        delta = np.linalg.norm(result - original, axis=1)
        protected_delta = {
            region: float(delta[list(masks[region])].max(initial=0.0))
            for region in protected
        }
        if any(value != 0 for value in protected_delta.values()):
            raise ValueError('Protected region displacement exceeded zero')
        reports.append({'region': 'waist', 'operation': edit['operation'],
                        'amount_pct': float(amount), 'mask_version': mask_spec()['schema_version'],
                        'changed_vertices': int(np.count_nonzero(delta > 0)),
                        'protected_max_delta': protected_delta})
    if not np.isfinite(result).all():
        raise ValueError('Body edit produced non-finite vertex coordinates')
    return result, reports
