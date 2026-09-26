from PIL import Image

from app.qa.bake_output_verification import verify_bake_output_set
from app.workers.bake_contract import compile_high_low_bake_contract


def _contract(resolution=8192, tiles=(1001, 1002)):
    return compile_high_low_bake_contract(
        "high.obj", "low.obj", udim_tiles=list(tiles), resolution=resolution,
    )


def test_real_8k_files_pass_verification(tmp_path):
    # Genuine 8192x8192 files written to disk -- not a stub or a claim. Solid
    # color keeps encode time and file size trivial while still being a real,
    # openable, correctly-dimensioned image.
    contract = _contract(resolution=8192, tiles=(1001,))
    resolved = {}
    for channel in contract.channels:
        path = tmp_path / f"{channel.name}.1001.jpg"
        Image.new("RGB", (8192, 8192), color=(100, 100, 100)).save(path, quality=80)
        resolved[(channel.name, 1001)] = str(path)

    report = verify_bake_output_set(contract, resolved)
    assert report.passed
    assert report.expected_count == len(contract.channels)
    assert all(f.width == 8192 and f.height == 8192 for f in report.files)
    assert all(f.sha256 for f in report.files)


def test_undersized_file_fails_resolution_check(tmp_path):
    contract = _contract(resolution=8192, tiles=(1001,))
    path = tmp_path / "normal.1001.jpg"
    Image.new("RGB", (2048, 2048), color=(128, 128, 255)).save(path, quality=80)
    resolved = {(ch.name, 1001): str(path) for ch in contract.channels}

    report = verify_bake_output_set(contract, resolved)
    assert not report.passed
    normal_result = next(f for f in report.files if f.channel == "normal")
    assert not normal_result.meets_expected_resolution
    assert any("below the contract" in b for b in normal_result.blockers)


def test_missing_file_on_disk_is_reported_not_silently_skipped(tmp_path):
    contract = _contract(resolution=2048, tiles=(1001,))
    resolved = {(ch.name, 1001): str(tmp_path / f"{ch.name}_never_written.jpg") for ch in contract.channels}
    report = verify_bake_output_set(contract, resolved)
    assert not report.passed
    assert all(not f.exists for f in report.files)


def test_zero_byte_file_fails_nonempty_check(tmp_path):
    contract = _contract(resolution=2048, tiles=(1001,))
    path = tmp_path / "ao.1001.jpg"
    path.write_bytes(b"")
    resolved = {(ch.name, 1001): str(path) for ch in contract.channels}
    report = verify_bake_output_set(contract, resolved)
    assert not report.passed
    assert all(not f.non_empty for f in report.files)


def test_unresolved_channel_tile_reported_as_missing_not_dropped(tmp_path):
    contract = _contract(resolution=2048, tiles=(1001, 1002))
    # Only resolve tile 1001, leaving 1002 entirely unresolved for every channel.
    resolved = {}
    for ch in contract.channels:
        path = tmp_path / f"{ch.name}.1001.jpg"
        Image.new("RGB", (2048, 2048), color=(1, 2, 3)).save(path, quality=80)
        resolved[(ch.name, 1001)] = str(path)

    report = verify_bake_output_set(contract, resolved)
    assert not report.passed
    assert len(report.missing) == len(contract.channels)  # one per channel @ tile 1002
    assert all("@1002" in m for m in report.missing)


def test_multi_tile_multi_channel_full_set_passes(tmp_path):
    contract = _contract(resolution=4096, tiles=(1001, 1002, 1003))
    resolved = {}
    for ch in contract.channels:
        for tile in contract.udim_tiles:
            path = tmp_path / f"{ch.name}.{tile}.jpg"
            Image.new("RGB", (4096, 4096), color=(10, 20, 30)).save(path, quality=70)
            resolved[(ch.name, tile)] = str(path)

    report = verify_bake_output_set(contract, resolved)
    assert report.passed
    assert report.expected_count == len(contract.channels) * len(contract.udim_tiles)
    assert report.passed_count == report.expected_count
