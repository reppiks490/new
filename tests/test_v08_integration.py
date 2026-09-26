from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.qa.production_gate import GateCheck, compile_production_gate
from app.runtime.leases import LeaseStore
from app.workers.bake_contract import compile_high_low_bake_contract
from app.workers.high_low_bake import (
    HighLowBakeReceipt,
    BakeChannelReceipt,
    build_high_low_bake_invocation,
    validate_bake_receipt,
)


def test_high_low_bake_invocation_is_background_and_autoexec_disabled():
    inv = build_high_low_bake_invocation("/opt/blender", "contract.json", "work", "bake.py")
    assert inv.command[0] == "/opt/blender"
    assert "--background" in inv.command
    assert "--disable-autoexec" in inv.command
    assert "--contract" in inv.command and "--workspace" in inv.command


def test_bake_receipt_requires_normal_and_ao():
    contract = compile_high_low_bake_contract("hi.glb", "lo.glb", cage_mesh="cage.glb", extreme=True)
    good = HighLowBakeReceipt(
        schema_name="character3d-high-low-bake-receipt-v1",
        status="succeeded",
        channels=[
            BakeChannelReceipt(channel="normal", executed=True, filepath="normal.<UDIM>.exr"),
            BakeChannelReceipt(channel="ambient_occlusion", executed=True, filepath="ao.<UDIM>.exr"),
        ],
    )
    assert validate_bake_receipt(contract, good) == []
    bad = good.model_copy(update={"channels": [BakeChannelReceipt(channel="normal", executed=True)]})
    assert validate_bake_receipt(contract, bad)


def test_composite_production_gate_preserves_domains():
    report = compile_production_gate([
        GateCheck(name="topology", passed=True, warnings=["minor note"]),
        GateCheck(name="identity", passed=False, blockers=["eye-region drift"]),
    ])
    assert not report.passed
    assert report.failed_checks == ["identity"]
    assert any("identity:" in x for x in report.blockers)
    assert any("topology:" in x for x in report.warnings)


def test_lease_control_plane(tmp_path: Path, monkeypatch):
    client = TestClient(app)
    db = tmp_path / "leases.db"
    monkeypatch.setenv("CHARACTER3D_LEASE_DB", str(db))
    r = client.post("/v1/runtime/leases/acquire", json={"worker_id": "gpu0", "owner_id": "jobA", "ttl_seconds": 30})
    assert r.status_code == 200
    lease = r.json()
    r = client.post("/v1/runtime/leases/heartbeat", json={"worker_id": "gpu0", "token": lease["token"], "ttl_seconds": 30})
    assert r.status_code == 200
    r = client.post("/v1/runtime/leases/release", json={"worker_id": "gpu0", "token": lease["token"]})
    assert r.status_code == 200 and r.json()["released"]


def test_production_gate_api():
    client = TestClient(app)
    payload = {"checks": [{"name": "geometry", "passed": True}, {"name": "groom", "passed": False, "blockers": ["penetration"]}]}
    r = client.post("/v1/qa/production-gate", json=payload)
    assert r.status_code == 200 and not r.json()["passed"]
