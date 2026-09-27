from __future__ import annotations

import json
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict

from app.workers.blender import BlenderInvocation
from app.workers.bake_contract import HighLowBakeContract


class BakeChannelReceipt(BaseModel):
    channel: str
    executed: bool
    # Legacy single-file shape: correct for a single-tile bake contract, one
    # file per channel. Left as-is for backward compatibility -- existing
    # receipts and callers keep working unchanged.
    filepath: str | None = None
    # UDIM tile -> filepath for this channel, for a multi-tile contract where
    # one channel produced a separate file per tile. Optional and additive:
    # when empty, callers fall back to `filepath` (single-tile case). When
    # populated, this is authoritative for multi-tile output verification
    # (see app/qa/bake_output_verification.py::validate_bake_receipt_and_output).
    tile_filepaths: dict[int, str] = Field(default_factory=dict)
    reason: str | None = None
    bit_depth: int | None = None
    samples: int | None = None


class HitMaskTile(BaseModel):
    hit_texels: int
    miss_texels: int
    miss_fraction: float | None = None


class HitMaskReport(BaseModel):
    resolution: int
    per_tile: dict[int, HitMaskTile] = Field(default_factory=dict)
    miss_fraction: float | None = None


class HighLowBakeReceipt(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    schema_name: str = Field(alias='schema')
    status: str
    channels: list[BakeChannelReceipt] = Field(default_factory=list)
    blender_version: str | None = None
    error: str | None = None
    # v2 worker evidence (absent on v1 receipts): measured high/low surface
    # deviation, the ray settings derived from it, which UDIM tiles the
    # low-poly UVs actually occupy, and the measured ray miss rate.
    deviation: dict | None = None
    ray: dict | None = None
    ao_distance: float | None = None
    uv_tiles: list[int] | None = None
    uncovered_contract_tiles: list[int] = Field(default_factory=list)
    uv_outside_contract_tiles: list[int] = Field(default_factory=list)
    hit_mask: HitMaskReport | None = None

    @property
    def executed_channels(self) -> set[str]:
        return {x.channel for x in self.channels if x.executed}


def write_bake_contract(contract: HighLowBakeContract, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(contract.model_dump(mode="json"), indent=2, sort_keys=True), encoding="utf-8")
    return p


def build_high_low_bake_invocation(
    blender_executable: str | Path,
    contract_path: str | Path,
    workspace: str | Path,
    worker_script: str | Path,
) -> BlenderInvocation:
    """Build a background Blender invocation for the selected-to-active bake worker.

    The worker script imports external geometry, so embedded .blend auto-execution is
    disabled. The receipt produced by Blender is the authoritative execution record.
    """
    return BlenderInvocation(
        executable=str(blender_executable),
        args=[
            "--background",
            "--disable-autoexec",
            "--python",
            str(worker_script),
            "--",
            "--contract",
            str(contract_path),
            "--workspace",
            str(workspace),
        ],
    )


def load_bake_receipt(path: str | Path) -> HighLowBakeReceipt:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(p)
    return HighLowBakeReceipt.model_validate_json(p.read_text(encoding="utf-8"))


def validate_bake_receipt(
    contract: HighLowBakeContract,
    receipt: HighLowBakeReceipt,
    *,
    require_channels: set[str] | None = None,
) -> list[str]:
    blockers: list[str] = []
    if receipt.status != "succeeded":
        blockers.append(f"Blender bake worker status is {receipt.status!r}.")
    expected = require_channels or {"normal", "ambient_occlusion"}
    missing = sorted(expected - receipt.executed_channels)
    if missing:
        blockers.append("Required bake channels were not executed: " + ", ".join(missing))
    if contract.blockers:
        blockers.append("Bake contract contains blockers: " + "; ".join(contract.blockers))
    if receipt.uncovered_contract_tiles:
        blockers.append(
            f"UDIM tile(s) {receipt.uncovered_contract_tiles} contain no low-poly UV islands; "
            "their baked images are empty."
        )
    if receipt.uv_outside_contract_tiles:
        blockers.append(
            f"Low-poly UVs occupy UDIM tile(s) {receipt.uv_outside_contract_tiles} that the contract does not bake."
        )
    mask = receipt.hit_mask
    if mask is not None and mask.miss_fraction is not None and mask.miss_fraction > contract.max_miss_fraction:
        blockers.append(
            f"{mask.miss_fraction:.1%} of UV-covered texels missed the high-poly (limit "
            f"{contract.max_miss_fraction:.1%}); increase ray_distance/cage_extrusion or supply a cage."
        )
    return blockers
