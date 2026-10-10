"""Deterministic surface garment recipes, not authored cloth-simulation assets."""
import json
from pathlib import Path

CATEGORIES = [('fashion', 200, 'Fashion'), ('custom', 80, 'Custom cut'),
              ('bikini', 40, 'Bikini'), ('lingerie', 20, 'Lingerie'), ('bodysuit', 20, 'Body suit')]
STYLES = ['Contour', 'Arc', 'Studio', 'Diagonal', 'Sculpt', 'Strata', 'Contour high', 'Drape', 'Horizon', 'Athletic']


def catalog() -> list[dict]:
    items = []
    for category, count, label in CATEGORIES:
        for i in range(count):
            items.append({'id': f'{category}-{i+1:03d}', 'category': category,
                          'name': f'{STYLES[i % 10]} {label} {i//10+1:02d}',
                          'design': i, 'construction': 'procedural_surface',
                          'coverage': 'mature' if category in {'bikini', 'lingerie', 'custom'} else 'standard',
                          'recipe': {'cut': i % 10, 'length': i // 10}})
    return items


def garment_mask(centers, bounds, item):
    import numpy as np
    h = bounds[1, 1]-bounds[0, 1]
    y = (centers[:, 1]-bounds[0, 1])/h
    x = np.abs(centers[:, 0])/h
    i, cat = item['design'], item['category']
    cut, layer = i % 10, i // 10
    collar = .78 + cut * .005
    hem = .43 + layer * .003
    # Each recipe changes geometric coverage, not merely its color.
    wave = np.sin(centers[:, 0] / h * (10 + cut)) * .009
    torso = (x < .17) & (y > hem + wave) & (y < collar - x * (cut % 3) * .2)
    if cat == 'fashion':
        return torso | ((y < .48 + cut*.003) & (y > .06 + layer*.012))
    if cat == 'bodysuit':
        return (y > .05 + i*.002) & (y < .81 + (i%5)*.005)
    if cat == 'custom':
        return ((x < .16) & (y > .62 + layer*.005) & (y < collar)) | ((y > .40 + cut*.003) & (y < .53))
    if cat == 'lingerie':
        return ((x < .16) & (y > .63 + cut*.0015) & (y < .76 + layer*.01)) | ((y > .43 + cut*.003) & (y < .54 + layer*.007))
    return ((x < .14) & (y > .68 + cut*.002) & (y < .75 + layer*.008)) | ((y > .46 + cut*.002) & (y < .53 + layer*.007))


def write_catalog():
    out = Path(__file__).parent / 'web/data/wardrobe.json'
    out.write_text(json.dumps(catalog(), separators=(',', ':')))


if __name__ == '__main__':
    write_catalog()
