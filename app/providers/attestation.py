from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

from pydantic import BaseModel

from app.providers.provenance import sha256_file


class HMACAttestation(BaseModel):
    schema_version: str = "character3d-hmac-attestation-v1"
    key_id: str
    algorithm: str = "HMAC-SHA256"
    artifact_sha256: str
    signature: str


def attest_file(path: str | Path, secret: bytes | str, *, key_id: str = "local") -> HMACAttestation:
    key = secret.encode("utf-8") if isinstance(secret, str) else secret
    if len(key) < 16:
        raise ValueError("attestation secret must be at least 16 bytes")
    digest = sha256_file(path)
    sig = hmac.new(key, digest.encode("ascii"), hashlib.sha256).hexdigest()
    return HMACAttestation(key_id=key_id, artifact_sha256=digest, signature=sig)


def verify_file_attestation(path: str | Path, envelope: HMACAttestation, secret: bytes | str) -> bool:
    key = secret.encode("utf-8") if isinstance(secret, str) else secret
    if sha256_file(path) != envelope.artifact_sha256:
        return False
    expected = hmac.new(key, envelope.artifact_sha256.encode("ascii"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, envelope.signature)
