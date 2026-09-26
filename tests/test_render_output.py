import pytest
from PIL import Image

from app.render.output_resolution import (
    RenderResolutionTier,
    estimate_render_buffer_gib,
    render_fits_hardware,
    render_output_spec_for_tier,
)
from app.render.output_verification import verify_render_output


def test_tier_resolutions_double_as_expected_and_16k_exceeds_8k():
    hd = render_output_spec_for_tier(RenderResolutionTier.HD)
    k8 = render_output_spec_for_tier(RenderResolutionTier.UHD_8K)
    k16 = render_output_spec_for_tier(RenderResolutionTier.UHD_16K)
    assert (hd.width, hd.height) == (1920, 1080)
    assert (k8.width, k8.height) == (7680, 4320)
    assert (k16.width, k16.height) == (15360, 8640)
    assert not k8.exceeds_8k
    assert k16.exceeds_8k
    assert k16.width == k8.width * 2 and k16.height == k8.height * 2


def test_overscan_extends_full_dimensions():
    spec = render_output_spec_for_tier(RenderResolutionTier.UHD_4K, overscan_px=100)
    assert spec.full_width == 3840 + 200
    assert spec.full_height == 2160 + 200


def test_buffer_estimate_scales_with_passes_and_bit_depth():
    single_pass = render_output_spec_for_tier(RenderResolutionTier.UHD_8K, passes=["combined"])
    multi_pass = render_output_spec_for_tier(RenderResolutionTier.UHD_8K, passes=["combined", "diffuse", "normal"])
    gib_single = estimate_render_buffer_gib(single_pass)
    gib_multi = estimate_render_buffer_gib(multi_pass)
    assert gib_multi == pytest.approx(gib_single * 3, rel=1e-9)

    low_depth = render_output_spec_for_tier(RenderResolutionTier.UHD_8K, bit_depth=8)
    high_depth = render_output_spec_for_tier(RenderResolutionTier.UHD_8K, bit_depth=32)
    assert estimate_render_buffer_gib(high_depth) == pytest.approx(estimate_render_buffer_gib(low_depth) * 4, rel=1e-9)


def test_render_fits_hardware_rejects_oversized_job_on_small_ram():
    spec = render_output_spec_for_tier(RenderResolutionTier.UHD_16K, bit_depth=32, passes=["combined", "diffuse", "normal", "depth"])
    fits, notes = render_fits_hardware(spec, ram_gb=8.0)
    assert not fits
    assert notes
    assert any("exceeds the conservative" in n for n in notes)


def test_render_fits_hardware_accepts_modest_job_on_ample_ram():
    spec = render_output_spec_for_tier(RenderResolutionTier.QHD)
    fits, notes = render_fits_hardware(spec, ram_gb=64.0)
    assert fits


def test_real_16k_output_file_passes_verification(tmp_path):
    # A genuine 15360x8640 file actually written to disk and actually
    # opened/verified -- not a stub, not a claim. Timing/size probed first
    # (1.9s, ~2MB for a solid-color JPEG) before committing to this in the
    # suite, same discipline as the earlier 8K bake-verification tests.
    spec = render_output_spec_for_tier(RenderResolutionTier.UHD_16K)
    path = tmp_path / "hero_render_16k.jpg"
    Image.new("RGB", (spec.width, spec.height), color=(90, 60, 40)).save(path, quality=80)

    result = verify_render_output(spec, path)
    assert result.passed
    assert result.width == 15360 and result.height == 8640
    assert result.sha256


def test_undersized_real_output_fails_verification(tmp_path):
    spec = render_output_spec_for_tier(RenderResolutionTier.UHD_8K)
    path = tmp_path / "too_small.jpg"
    Image.new("RGB", (1920, 1080), color=(1, 2, 3)).save(path, quality=80)

    result = verify_render_output(spec, path)
    assert not result.passed
    assert any("below the required" in b for b in result.blockers)


def test_missing_render_output_reported_not_silently_skipped(tmp_path):
    spec = render_output_spec_for_tier(RenderResolutionTier.HD)
    result = verify_render_output(spec, tmp_path / "never_rendered.jpg")
    assert not result.exists
    assert not result.passed


def test_zero_byte_render_output_fails():
    import tempfile
    from pathlib import Path as _Path
    with tempfile.TemporaryDirectory() as d:
        p = _Path(d) / "empty.jpg"
        p.write_bytes(b"")
        spec = render_output_spec_for_tier(RenderResolutionTier.HD)
        result = verify_render_output(spec, p)
        assert not result.non_empty
        assert not result.passed


def test_decompression_bomb_guard_is_raised_but_still_bounded_not_disabled():
    from PIL import Image as PILImage
    # Confirms app/qa/textures.py deliberately raised PIL's default guard to
    # accommodate this project's own 16K ceiling, rather than disabling it
    # outright (None would mean "no limit at all").
    assert PILImage.MAX_IMAGE_PIXELS is not None
    assert PILImage.MAX_IMAGE_PIXELS == 200_000_000
    # The 16K tier (132,710,400 px) must fit comfortably under the raised
    # cap, and the cap must still be well below "unlimited".
    from app.render.output_resolution import RenderResolutionTier, render_output_spec_for_tier
    spec = render_output_spec_for_tier(RenderResolutionTier.UHD_16K)
    assert spec.width * spec.height < PILImage.MAX_IMAGE_PIXELS
