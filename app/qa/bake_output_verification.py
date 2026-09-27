from __future__ import annotations

from pathlib import Path
from pydantic import BaseModel, Field

from app.providers.provenance import sha256_file
from app.qa.textures import inspect_texture
from app.workers.bake_contract import HighLowBakeContract
from app.workers.high_low_bake import HighLowBakeReceipt, validate_bake_receipt


class BakeFileVerification(BaseModel):
    channel: str
    tile: int
    path: str
    exists: bool
    width: int | None = None
    height: int | None = None
    meets_expected_resolution: bool = False
    non_empty: bool = False
    sha256: str | None = None
    blockers: list[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.exists and self.non_empty and self.meets_expected_resolution and not self.blockers


class BakeSetVerificationReport(BaseModel):
    resolution: int
    expected_count: int
    verified_count: int
    passed_count: int
    files: list[BakeFileVerification] = Field(default_factory=list)
    # "channel@tile" identifiers the contract requires but that had no
    # resolved path supplied at all -- distinct from a resolved path whose
    # file turned out not to exist, which shows up in `files` instead.
    missing: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.blockers and not self.missing and self.passed_count == self.expected_count


def _image_dimensions(p: Path) -> tuple[int, int]:
    # Bakes are written as OpenEXR (float precision), which PIL cannot open.
    from app.render.output_verification import EXR_MAGIC, exr_dimensions
    import struct

    with open(p, "rb") as fh:
        magic = fh.read(4)
    if magic == struct.pack("<i", EXR_MAGIC):
        return exr_dimensions(p)
    report = inspect_texture(p)
    return report.width, report.height


def verify_bake_output_set(
    contract: HighLowBakeContract,
    resolved_paths: dict[tuple[str, int], str],
    *,
    channels: set[str] | None = None,
) -> BakeSetVerificationReport:
    """Verify every (channel, UDIM tile) a bake contract requires actually
    exists on disk as a real image at the expected resolution, is non-empty,
    and is content-hashed.

    This closes a real gap: app/workers/bake_contract.py::validate_bake_receipt
    only checks that a Blender worker's OWN receipt claims a channel executed
    (`receipt.executed_channels`) -- it never opens the resulting files. A
    receipt can claim success while a file is missing, truncated, or the
    wrong resolution. This function actually opens each file (reusing
    app/qa/textures.py's real per-file image inspection) and hashes it
    (reusing app/providers/provenance.py's real SHA-256), rather than
    trusting a claim.
    """
    names = [ch.name for ch in contract.channels if channels is None or ch.name in channels]
    expected_keys = [(name, tile) for name in names for tile in contract.udim_tiles]
    files: list[BakeFileVerification] = []
    missing: list[str] = []
    blockers: list[str] = []

    for channel, tile in expected_keys:
        path = resolved_paths.get((channel, tile))
        if path is None:
            missing.append(f"{channel}@{tile}")
            continue

        p = Path(path)
        if not p.is_file():
            files.append(BakeFileVerification(
                channel=channel, tile=tile, path=str(p), exists=False,
                blockers=[f"{p} does not exist."],
            ))
            continue

        non_empty = p.stat().st_size > 0
        file_blockers: list[str] = []
        width = height = None
        meets = False
        if not non_empty:
            file_blockers.append("File exists but is zero bytes.")
        else:
            try:
                width, height = _image_dimensions(p)
                meets = max(width, height) >= contract.resolution
                if not meets:
                    file_blockers.append(
                        f"Resolution {width}x{height} is below the contract's required {contract.resolution}."
                    )
            except Exception as exc:
                file_blockers.append(f"Could not read image: {exc}")

        digest = sha256_file(p) if non_empty else None
        files.append(BakeFileVerification(
            channel=channel, tile=tile, path=str(p), exists=True,
            width=width, height=height, meets_expected_resolution=meets,
            non_empty=non_empty, sha256=digest, blockers=file_blockers,
        ))

    passed_count = sum(1 for f in files if f.passed)
    if missing:
        blockers.append(f"{len(missing)} expected bake file(s) have no resolved path at all: {missing}")

    return BakeSetVerificationReport(
        resolution=contract.resolution,
        expected_count=len(expected_keys),
        verified_count=len(files),
        passed_count=passed_count,
        files=files,
        missing=missing,
        blockers=blockers,
    )


def validate_bake_receipt_and_output(
    contract: HighLowBakeContract,
    receipt: HighLowBakeReceipt,
    *,
    require_channels: set[str] | None = None,
) -> tuple[list[str], BakeSetVerificationReport | None]:
    """Combine the receipt-claim check (validate_bake_receipt -- did the
    Blender worker's own receipt claim each required channel executed) with
    real on-disk file verification (verify_bake_output_set), closing the gap
    where a receipt could claim success while its files are missing,
    truncated, or undersized.

    Multi-tile contracts: `BakeChannelReceipt.tile_filepaths` (UDIM tile ->
    filepath, per channel) is the authoritative source when a channel
    populates it. The legacy single `filepath` field is used only as a
    fallback for single-tile contracts, exactly as before -- it is never
    used to guess which tile a file belongs to on a multi-tile contract,
    since one path cannot correctly stand in for N tiles' worth of files.
    If a multi-tile contract's receipt never populates `tile_filepaths` at
    all, this function still can't verify anything and returns None for the
    output report, same as before this schema was extended.
    """
    blockers = validate_bake_receipt(contract, receipt, require_channels=require_channels)

    single_tile = len(contract.udim_tiles) == 1
    any_tile_filepaths = any(ch.tile_filepaths for ch in receipt.channels)
    if not single_tile and not any_tile_filepaths:
        return blockers, None

    resolved_paths: dict[tuple[str, int], str] = {}
    for ch in receipt.channels:
        if not ch.executed:
            continue
        if ch.tile_filepaths:
            for tile, path in ch.tile_filepaths.items():
                resolved_paths[(ch.channel, tile)] = path
        elif ch.filepath and single_tile:
            resolved_paths[(ch.channel, contract.udim_tiles[0])] = ch.filepath

    # Verify what is required plus anything the receipt claims it produced;
    # channels no worker can bake (and that nobody required) aren't demanded.
    expected_channels = set(require_channels or {"normal", "ambient_occlusion"}) | receipt.executed_channels
    output_report = verify_bake_output_set(contract, resolved_paths, channels=expected_channels)
    if not output_report.passed:
        blockers = list(blockers)
        blockers.extend(f"Bake output verification: {b}" for b in output_report.blockers)
        blockers.extend(
            f"Bake output verification: {f.channel}@{f.tile}: " + "; ".join(f.blockers)
            for f in output_report.files if not f.passed
        )
    return blockers, output_report
