from __future__ import annotations

import json
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict

from app.workers.blender import BlenderInvocation
from app.workers.bake_contract import HighLowBakeContract


class BakeChannelReceipt(BaseModel):
    channel: str
    executed: bool
    filepath: str | None = None
    reason: str | None = None


class HighLowBakeReceipt(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    schema_name: str = Field(alias='schema')
    status: str
    channels: list[BakeChannelReceipt] = Field(default_factory=list)
    blender_version: str | None = None
    error: str | None = None

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
    return blockers
