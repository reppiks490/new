from __future__ import annotations

import re
from pathlib import Path

from app.providers.execution import CanonicalTaskStatus, ProviderTaskSnapshot, RemoteAsset, download_verified_asset, write_provenance_receipt
from app.providers.hi3d import TRUSTED_ASSET_HOSTS as HI3D_HOSTS
from app.providers.ledger import ProviderLedger
from app.providers.meshy import TRUSTED_ASSET_HOSTS as MESHY_HOSTS
from app.providers.models import ProviderId
from app.providers.provenance import AssetProvenance, save_asset_provenance
from app.providers.tripo import TRUSTED_ASSET_HOSTS as TRIPO_HOSTS


TRUSTED_HOSTS = {
    ProviderId.TRIPO: TRIPO_HOSTS,
    ProviderId.MESHY: MESHY_HOSTS,
    ProviderId.HI3D: HI3D_HOSTS,
}

_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def _safe_component(value: str, fallback: str) -> str:
    value = _SAFE.sub("_", value).strip("._")
    return value[:96] or fallback


def ingest_terminal_snapshot(
    snapshot: ProviderTaskSnapshot,
    workspace: str | Path,
    *,
    ledger: ProviderLedger | None = None,
    max_asset_bytes: int = 2_000_000_000,
) -> ProviderTaskSnapshot:
    if snapshot.status != CanonicalTaskStatus.SUCCEEDED:
        raise ValueError("Only succeeded provider snapshots can be ingested")
    if snapshot.provider not in TRUSTED_HOSTS:
        raise ValueError(f"No trusted-host policy for provider {snapshot.provider}")
    if not snapshot.task_id:
        raise ValueError("Provider snapshot is missing task_id")

    root = Path(workspace) / "providers" / snapshot.provider.value / _safe_component(snapshot.task_id, "task")
    root.mkdir(parents=True, exist_ok=True)
    if ledger:
        ledger.upsert_snapshot(snapshot)

    ingested: list[RemoteAsset] = []
    for index, asset in enumerate(snapshot.assets):
        fmt = _safe_component((asset.format or "bin").lower(), "bin")
        kind = _safe_component(asset.kind, "asset")
        dest = root / f"{index:02d}_{kind}.{fmt}"
        downloaded = download_verified_asset(
            asset.url,
            dest,
            allowed_hosts=TRUSTED_HOSTS[snapshot.provider],
            max_bytes=max_asset_bytes,
            expected_sha256=asset.sha256,
        )
        downloaded.kind = asset.kind
        downloaded.format = asset.format or downloaded.format
        ingested.append(downloaded)
        prov = AssetProvenance(
            provider=snapshot.provider,
            task_id=snapshot.task_id,
            provider_asset_url=asset.url,
            local_path=downloaded.local_path or str(dest),
            sha256=downloaded.sha256 or "",
            size_bytes=downloaded.size_bytes or 0,
            format=downloaded.format,
            metadata={"kind": asset.kind},
        )
        save_asset_provenance(prov, root / f"{index:02d}_{kind}.provenance.json")
        if ledger:
            ledger.record_asset(snapshot.provider, snapshot.task_id, downloaded)

    admitted = snapshot.model_copy(update={"assets": ingested, "metadata": {**snapshot.metadata, "locally_ingested": True}})
    write_provenance_receipt(admitted, root / "provider-receipt.json")
    if ledger:
        ledger.upsert_snapshot(admitted)
    return admitted
