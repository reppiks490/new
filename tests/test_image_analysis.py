import numpy as np
import pytest
from PIL import Image

from app.core.models import TextureTier
from app.pipeline.image_analysis import analyze_image_for_prompt


def _write_split_image(path, size=(200, 100), left=(200, 30, 30), right=(30, 30, 200)):
    arr = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    mid = size[0] // 2
    arr[:, :mid] = left
    arr[:, mid:] = right
    Image.fromarray(arr).save(path)
    return path


def test_dominant_colors_match_a_known_split_image(tmp_path):
    path = _write_split_image(tmp_path / "split.png")
    hints = analyze_image_for_prompt(path, palette_size=4)
    assert hints.width == 200 and hints.height == 100
    rgbs = {c.rgb for c in hints.dominant_colors}
    assert (200, 30, 30) in rgbs
    assert (30, 30, 200) in rgbs
    proportions = {c.rgb: c.proportion for c in hints.dominant_colors}
    assert abs(proportions[(200, 30, 30)] - 0.5) < 0.01
    assert abs(proportions[(30, 30, 200)] - 0.5) < 0.01
    # Proportions across the whole extracted palette must sum to ~1.
    assert abs(sum(c.proportion for c in hints.dominant_colors) - 1.0) < 0.01


def test_flat_solid_image_has_near_zero_contrast_and_edges(tmp_path):
    path = tmp_path / "flat.png"
    Image.new("RGB", (256, 256), color=(128, 128, 128)).save(path)
    hints = analyze_image_for_prompt(path)
    assert hints.contrast_std < 1.0
    assert hints.edge_density < 1.0
    assert any("low contrast" in w for w in hints.warnings)


def test_high_contrast_checkerboard_has_higher_edge_density_than_flat(tmp_path):
    flat_path = tmp_path / "flat.png"
    Image.new("RGB", (256, 256), color=(100, 100, 100)).save(flat_path)

    checker = np.zeros((256, 256), dtype=np.uint8)
    checker[::2, ::2] = 255
    checker[1::2, 1::2] = 255
    checker_path = tmp_path / "checker.png"
    Image.fromarray(checker).convert("RGB").save(checker_path)

    flat_hints = analyze_image_for_prompt(flat_path)
    checker_hints = analyze_image_for_prompt(checker_path)
    assert checker_hints.edge_density > flat_hints.edge_density
    assert checker_hints.contrast_std > flat_hints.contrast_std


def test_small_image_triggers_resolution_warning_and_2k_suggestion(tmp_path):
    path = tmp_path / "tiny.png"
    Image.new("RGB", (128, 128), color=(50, 60, 70)).save(path)
    hints = analyze_image_for_prompt(path)
    assert any("512px" in w for w in hints.warnings)
    assert hints.suggested_texture_tier == TextureTier.T2K


def test_large_image_suggests_8k_texture_tier(tmp_path):
    path = tmp_path / "big.jpg"
    Image.new("RGB", (8192, 4096), color=(80, 90, 100)).save(path, quality=70)
    hints = analyze_image_for_prompt(path)
    assert hints.suggested_texture_tier == TextureTier.T8K


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        analyze_image_for_prompt("/nonexistent/path.png")


def test_invalid_palette_size_rejected(tmp_path):
    path = tmp_path / "flat.png"
    Image.new("RGB", (64, 64), color=(1, 2, 3)).save(path)
    with pytest.raises(ValueError):
        analyze_image_for_prompt(path, palette_size=0)
