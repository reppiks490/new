import hashlib
import hmac
import json
from pathlib import Path

import httpx
import trimesh

from app.providers.execution import CanonicalTaskStatus, ProviderTaskSnapshot, RemoteAsset, download_verified_asset
from app.providers.geometry import candidate_metrics_from_mesh, inspect_mesh
from app.providers.ledger import ProviderLedger
from app.providers.models import ProviderId
from app.providers.webhooks import accept_advisory_webhook, accept_tripo_webhook


class FakeTransport:
    def __init__(self, response: httpx.Response):
        self.response = response

    def request(self, method: str, url: str, **kwargs):
        return self.response


def response(url: str, body: bytes, *, headers=None, status=200):
    return httpx.Response(status, content=body, headers=headers or {}, request=httpx.Request("GET", url))


def test_streaming_download_hashes_and_writes_atomically(tmp_path: Path):
    payload = b"mesh-bytes" * 1024
    out = tmp_path / "asset.glb"
    got = download_verified_asset(
        "https://assets.meshy.ai/a.glb",
        out,
        allowed_hosts={"assets.meshy.ai"},
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        transport=FakeTransport(response("https://assets.meshy.ai/a.glb", payload)),
        chunk_size=128,
    )
    assert out.read_bytes() == payload
    assert got.size_bytes == len(payload)
    assert not (tmp_path / "asset.glb.part").exists()


def test_download_rejects_untrusted_redirect_target(tmp_path: Path):
    evil = response("https://evil.example/payload.glb", b"x")
    try:
        download_verified_asset(
            "https://assets.meshy.ai/a.glb",
            tmp_path / "a.glb",
            allowed_hosts={"assets.meshy.ai"},
            transport=FakeTransport(evil),
        )
        assert False, "expected redirect-host rejection"
    except ValueError as exc:
        assert "untrusted host" in str(exc)


def test_download_size_cap_removes_partial(tmp_path: Path):
    payload = b"0123456789"
    out = tmp_path / "big.glb"
    try:
        download_verified_asset(
            "https://assets.meshy.ai/big.glb",
            out,
            allowed_hosts={"assets.meshy.ai"},
            max_bytes=4,
            transport=FakeTransport(response("https://assets.meshy.ai/big.glb", payload)),
            chunk_size=2,
        )
        assert False, "expected size cap"
    except ValueError:
        pass
    assert not out.exists()
    assert not (tmp_path / "big.glb.part").exists()


def test_provider_ledger_upserts_and_deduplicates_delivery(tmp_path: Path):
    ledger = ProviderLedger(tmp_path / "provider.sqlite3")
    snap = ProviderTaskSnapshot(
        provider=ProviderId.MESHY,
        task_id="m1",
        status=CanonicalTaskStatus.RUNNING,
        assets=[RemoteAsset(kind="model", url="https://assets.meshy.ai/a.glb", format="glb")],
    )
    ledger.upsert_snapshot(snap)
    assert ledger.get_task(ProviderId.MESHY, "m1")["status"] == "running"
    assert len(ledger.list_assets(ProviderId.MESHY, "m1")) == 1
    assert ledger.record_delivery(ProviderId.MESHY, "delivery", b"{}") is True
    assert ledger.record_delivery(ProviderId.MESHY, "delivery", b"{}") is False


def test_signed_tripo_webhook_is_authoritative_and_deduped(tmp_path: Path):
    ledger = ProviderLedger(tmp_path / "provider.sqlite3")
    body = json.dumps({
        "type": "task.completed",
        "data": {"task_id": "t1", "status": "success", "output": {"model_url": "https://cdn.tripo3d.ai/a.glb"}},
    }, separators=(",", ":")).encode()
    ts = 1_700_000_000
    secret = "whsec_test"
    sig = hmac.new(secret.encode(), str(ts).encode() + b"." + body, hashlib.sha256).hexdigest()
    d1 = accept_tripo_webhook(body, signature_header=f"t={ts},v1={sig}", delivery_id="d1", secret=secret, ledger=ledger, now=ts)
    assert d1.accepted and d1.cryptographically_verified and d1.authoritative_terminal_state
    d2 = accept_tripo_webhook(body, signature_header=f"t={ts},v1={sig}", delivery_id="d1", secret=secret, ledger=ledger, now=ts)
    assert d2.accepted and d2.duplicate


def test_meshy_webhook_remains_advisory(tmp_path: Path):
    ledger = ProviderLedger(tmp_path / "provider.sqlite3")
    body = json.dumps({"id": "m2", "status": "SUCCEEDED", "progress": 100, "model_urls": {"glb": "https://assets.meshy.ai/a.glb"}}).encode()
    decision = accept_advisory_webhook(ProviderId.MESHY, body, ledger=ledger)
    assert decision.accepted
    assert decision.requery_required
    assert not decision.authoritative_terminal_state
    assert not decision.cryptographically_verified


def test_local_mesh_inspection_measures_topology(tmp_path: Path):
    mesh = trimesh.creation.box(extents=(1, 2, 3))
    path = tmp_path / "box.obj"
    mesh.export(path)
    inspection = inspect_mesh(path)
    assert inspection.faces == 12
    assert inspection.vertices == 8
    assert inspection.watertight
    assert inspection.manifold_edge_ratio == 1.0
    assert inspection.degenerate_face_ratio == 0.0


def test_mesh_inspection_feeds_provider_neutral_candidate_metrics(tmp_path: Path):
    mesh = trimesh.creation.icosphere(subdivisions=1)
    path = tmp_path / "sphere.obj"
    mesh.export(path)
    inspection = inspect_mesh(path)
    metrics = candidate_metrics_from_mesh(ProviderId.HI3D, inspection, pbr_channel_count=4, max_texture_resolution=8192)
    assert metrics.provider == ProviderId.HI3D
    assert metrics.face_count == inspection.faces
    assert metrics.manifold_ratio > 0.99
