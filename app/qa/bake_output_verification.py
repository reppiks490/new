from __future__ import annotations

from pathlib import Path
from pydantic import BaseModel, Field

from app.providers.provenance import sha256_file
from app.qa.textures import inspect_texture
from app.workers.bake_contract import HighLowBakeContract


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


def verify_bake_output_set(
    contract: HighLowBakeContract,
    resolved_paths: dict[tuple[str, int], str],
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
    expected_keys = [(ch.name, tile) for ch in contract.channels for tile in contract.udim_tiles]
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
                texture_report = inspect_texture(p)
                width, height = texture_report.width, texture_report.height
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
