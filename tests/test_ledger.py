from pathlib import Path

from app.providers.execution import CanonicalTaskStatus, ProviderTaskSnapshot, RemoteAsset
from app.providers.models import ProviderId
from app.runtime.ledger import ProviderLedger


def test_provider_ledger_roundtrip(tmp_path: Path):
    db = ProviderLedger(tmp_path / "ledger.sqlite3")
    snap = ProviderTaskSnapshot(provider=ProviderId.TRIPO, task_id="t1", status=CanonicalTaskStatus.SUCCEEDED, progress=100, assets=[RemoteAsset(kind="model", url="https://cdn.tripo3d.ai/model.glb", format="glb", sha256="abc", local_path="/tmp/model.glb", size_bytes=123)])
    db.upsert_snapshot(snap)
    got = db.get_task("tripo", "t1")
    assert got is not None
    assert got["status"] == "succeeded"
    assert got["assets"][0]["sha256"] == "abc"
    db.close()
