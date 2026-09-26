from PIL import Image

from app.qa.bake_output_verification import validate_bake_receipt_and_output
from app.workers.bake_contract import compile_high_low_bake_contract
from app.workers.high_low_bake import BakeChannelReceipt, HighLowBakeReceipt


def _contract(resolution=2048, tiles=(1001,)):
    return compile_high_low_bake_contract("high.obj", "low.obj", udim_tiles=list(tiles), resolution=resolution)


def _receipt(channels):
    return HighLowBakeReceipt(schema="high-low-bake-v1", status="succeeded", channels=channels)


def test_receipt_claims_success_but_file_missing_on_disk_is_caught(tmp_path):
    # This is the exact gap this function closes: validate_bake_receipt alone
    # would pass this (receipt says succeeded, required channels executed),
    # but the file was never actually written.
    contract = _contract(tiles=(1001,))
    receipt = _receipt([
        BakeChannelReceipt(channel="normal", executed=True, filepath=str(tmp_path / "normal_never_written.png")),
        BakeChannelReceipt(channel="ambient_occlusion", executed=True, filepath=str(tmp_path / "ao_never_written.png")),
    ])
    blockers, report = validate_bake_receipt_and_output(contract, receipt)
    assert report is not None
    assert not report.passed
    assert any("does not exist" in f.blockers[0] for f in report.files)
    assert any("output verification" in b.lower() for b in blockers)


def test_receipt_and_real_files_both_pass(tmp_path):
    contract = _contract(resolution=2048, tiles=(1001,))
    # verify_bake_output_set checks EVERY channel the contract declares
    # (normal, displacement, ambient_occlusion, curvature, thickness by
    # default), independent of require_channels -- which only narrows the
    # separate receipt-claim gate. So a real "both pass" case needs a file
    # for each declared channel, not just the required ones.
    channels = []
    for ch in contract.channels:
        path = tmp_path / f"{ch.name}.png"
        Image.new("RGB", (2048, 2048), color=(50, 60, 70)).save(path)
        channels.append(BakeChannelReceipt(channel=ch.name, executed=True, filepath=str(path)))
    receipt = _receipt(channels)

    blockers, report = validate_bake_receipt_and_output(contract, receipt, require_channels={"normal", "ambient_occlusion"})
    assert blockers == []
    assert report is not None
    assert report.passed


def test_multi_tile_contract_skips_output_verification_with_clear_reason(tmp_path):
    contract = _contract(resolution=2048, tiles=(1001, 1002))
    receipt = _receipt([
        BakeChannelReceipt(channel="normal", executed=True, filepath=str(tmp_path / "normal.png")),
    ])
    blockers, report = validate_bake_receipt_and_output(contract, receipt)
    # Output verification is honestly skipped (None), not silently wrong --
    # the receipt schema can't represent per-tile paths for a multi-tile
    # contract, so this function doesn't pretend it can.
    assert report is None
    # Receipt-claim blockers (e.g. missing required "ambient_occlusion")
    # still apply independently of the output-verification limitation.
    assert any("ambient_occlusion" in b for b in blockers)


def test_undersized_real_file_is_caught_even_though_receipt_claims_success(tmp_path):
    contract = _contract(resolution=4096, tiles=(1001,))
    path = tmp_path / "normal.png"
    Image.new("RGB", (512, 512), color=(10, 20, 30)).save(path)  # far below the 4K contract
    receipt = _receipt([
        BakeChannelReceipt(channel="normal", executed=True, filepath=str(path)),
        BakeChannelReceipt(channel="ambient_occlusion", executed=True, filepath=str(path)),
    ])
    blockers, report = validate_bake_receipt_and_output(contract, receipt, require_channels={"normal", "ambient_occlusion"})
    assert report is not None
    assert not report.passed
    assert any("below the contract" in b for b in blockers)


def test_multi_tile_receipt_with_tile_filepaths_is_fully_verified(tmp_path):
    contract = _contract(resolution=2048, tiles=(1001, 1002))
    channels = []
    for ch in contract.channels:
        tile_paths = {}
        for tile in contract.udim_tiles:
            path = tmp_path / f"{ch.name}_{tile}.png"
            Image.new("RGB", (2048, 2048), color=(20, 30, 40)).save(path)
            tile_paths[tile] = str(path)
        channels.append(BakeChannelReceipt(channel=ch.name, executed=True, tile_filepaths=tile_paths))
    receipt = _receipt(channels)

    blockers, report = validate_bake_receipt_and_output(contract, receipt)
    assert report is not None
    assert report.passed
    assert report.expected_count == len(contract.channels) * len(contract.udim_tiles)
    assert blockers == []


def test_multi_tile_receipt_catches_one_missing_tile_file(tmp_path):
    contract = _contract(resolution=2048, tiles=(1001, 1002))
    channels = []
    for ch in contract.channels:
        tile_paths = {}
        for tile in contract.udim_tiles:
            path = tmp_path / f"{ch.name}_{tile}.png"
            if tile == 1002 and ch.name == "normal":
                # Deliberately never write this one file -- the exact case
                # this function exists to catch even when everything else
                # in the receipt looks fine.
                pass
            else:
                Image.new("RGB", (2048, 2048), color=(20, 30, 40)).save(path)
            tile_paths[tile] = str(path)
        channels.append(BakeChannelReceipt(channel=ch.name, executed=True, tile_filepaths=tile_paths))
    receipt = _receipt(channels)

    blockers, report = validate_bake_receipt_and_output(contract, receipt)
    assert report is not None
    assert not report.passed
    missing_entry = next(f for f in report.files if f.channel == "normal" and f.tile == 1002)
    assert not missing_entry.exists
    assert any("normal@1002" in b for b in blockers)


def test_legacy_single_filepath_on_multi_tile_receipt_is_not_guessed():
    # A channel using the OLD single-filepath field on a multi-tile contract,
    # with no tile_filepaths anywhere in the receipt: must not be silently
    # attributed to any tile.
    contract = _contract(resolution=2048, tiles=(1001, 1002))
    receipt = _receipt([
        BakeChannelReceipt(channel="normal", executed=True, filepath="/tmp/whatever.png"),
    ])
    blockers, report = validate_bake_receipt_and_output(contract, receipt)
    assert report is None


def test_mixed_legacy_and_tile_filepaths_in_same_multi_tile_receipt(tmp_path):
    # One channel uses the new tile_filepaths field (multi-tile aware);
    # another only has the legacy single filepath and gets correctly
    # excluded from verification rather than guessed at.
    contract = _contract(resolution=2048, tiles=(1001, 1002))
    tile_paths = {}
    for tile in contract.udim_tiles:
        path = tmp_path / f"normal_{tile}.png"
        Image.new("RGB", (2048, 2048), color=(5, 5, 5)).save(path)
        tile_paths[tile] = str(path)

    channels = [
        BakeChannelReceipt(channel="normal", executed=True, tile_filepaths=tile_paths),
        BakeChannelReceipt(channel="ambient_occlusion", executed=True, filepath="/tmp/legacy_ao.png"),
    ]
    receipt = _receipt(channels)
    blockers, report = validate_bake_receipt_and_output(contract, receipt)
    assert report is not None  # verification runs because at least one channel has tile_filepaths
    # "normal" is fully resolved and real; "ambient_occlusion" contributes no
    # resolved (channel, tile) pairs at all via the legacy field, so it shows
    # up as missing for both tiles rather than being guessed at.
    assert any("ambient_occlusion@1001" in m for m in report.missing)
    assert any("ambient_occlusion@1002" in m for m in report.missing)
    normal_files = [f for f in report.files if f.channel == "normal"]
    assert len(normal_files) == 2
    assert all(f.passed for f in normal_files)
