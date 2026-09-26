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
