"""QA59: distinguish a successful decode from full cinematic master integrity.

Uses disposable synthetic H.264 FFmpeg media and SQLite; never owner footage.
This is an opt-in strict CLI gate, preserving decode-only default behavior.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
QA58 = ROOT / "tests" / "test_cinematic_master_sha_attestation_qa58.py"
spec = importlib.util.spec_from_file_location("qa58_helpers_for_qa59", QA58)
assert spec and spec.loader
qa58 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa58)
mod = qa58.mod


def _invoke(monkeypatch, capsys, workspace: Path, db: Path, *, strict: bool):
    argv = ["master-audit", "--workspace", str(workspace), "--database", str(db)]
    if strict:
        argv.append("--require-integrity")
    monkeypatch.setattr(sys, "argv", argv)
    code = mod.main()
    report = json.loads(capsys.readouterr().out)
    assert report.get("safe_to_delete_automatically") is False
    assert "PRIVATE_QA58_PROMPT_SENTINEL" not in json.dumps(report)
    assert not any("path" in key or "sha256" in key for key in report)
    return code, report


def test_strict_clean_real_master_passes(tmp_path, monkeypatch, capsys):
    media, db, workspace = qa58._workspace(tmp_path)
    qa58._record(db, 1, hashlib.sha256(media.read_bytes()).hexdigest())
    code, report = _invoke(monkeypatch, capsys, workspace, db, strict=True)
    assert code == 0
    assert report["integrity_attestation_complete"] is True


def test_decodable_but_hash_mismatched_fails_strict(tmp_path, monkeypatch, capsys):
    media, db, workspace = qa58._workspace(tmp_path)
    qa58._record(db, 1, "0" * 64)
    default_code, default_report = _invoke(monkeypatch, capsys, workspace, db, strict=False)
    assert default_code == 0  # backward-compatible decode-only result
    assert default_report["verification_complete"] is True
    code, report = _invoke(monkeypatch, capsys, workspace, db, strict=True)
    assert code == 1
    assert report["hash_mismatch_count"] == 1
    assert report["integrity_attestation_complete"] is False


def test_legacy_missing_hash_is_unattested_not_strict_success(tmp_path, monkeypatch, capsys):
    media, db, workspace = qa58._workspace(tmp_path)
    qa58._record(db, 1, None)
    code, report = _invoke(monkeypatch, capsys, workspace, db, strict=True)
    assert code == 1
    assert report["verified_decodable_masters"] == 1
    assert report["hash_mismatch_count"] == 0
    assert report["integrity_attestation_complete"] is False


def test_correct_hash_but_false_fps_claim_fails_strict(tmp_path, monkeypatch, capsys):
    media, db, workspace = qa58._workspace(tmp_path)
    qa58._record(db, 1, hashlib.sha256(media.read_bytes()).hexdigest())
    import sqlite3
    from contextlib import closing
    with closing(sqlite3.connect(db)) as conn:
        rowid, raw = conn.execute("SELECT id,data FROM records").fetchone()
        payload = json.loads(raw)
        payload["delivery_fps"] = 12
        conn.execute("UPDATE records SET data=? WHERE id=?", (json.dumps(payload), rowid))
        conn.commit()
    code, report = _invoke(monkeypatch, capsys, workspace, db, strict=True)
    assert code == 1
    assert report["verified_decodable_masters"] == 1
    assert report["hash_attested_masters"] == 1
    assert report["timing_anomaly_count"] == 1
    assert report["integrity_attestation_complete"] is False
