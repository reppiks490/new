from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel

from app.release.canonical import CanonicalReleaseManifest, verify_canonical_manifest
from app.security.release_signing import ReleaseSignature, sign_release, verify_release


class SignedCanonicalManifest(BaseModel):
    schema_version: str = 'character3d-signed-canonical-v1'
    canonical_manifest_sha256: str
    public_key_fingerprint_sha256: str
    signature: ReleaseSignature


def _public_key_fingerprint(pem: str) -> str:
    return hashlib.sha256(pem.encode('utf-8')).hexdigest()


def sign_canonical_manifest(
    manifest_path: str | Path,
    private_key_pem: bytes,
    *,
    key_id: str = 'canonical-release',
    signed_at: int | None = None,
    require_releasable: bool = True,
) -> SignedCanonicalManifest:
    p = Path(manifest_path)
    manifest = CanonicalReleaseManifest.model_validate_json(p.read_text(encoding='utf-8'))
    if not verify_canonical_manifest(manifest):
        raise ValueError('canonical manifest digest verification failed')
    if require_releasable and not manifest.releasable:
        raise ValueError('canonical manifest is not releasable; refusing release signature')
    sig = sign_release(p, private_key_pem, key_id=key_id, signed_at=signed_at)
    return SignedCanonicalManifest(
        canonical_manifest_sha256=manifest.manifest_sha256,
        public_key_fingerprint_sha256=_public_key_fingerprint(sig.public_key_pem),
        signature=sig,
    )


def verify_signed_canonical_manifest(manifest_path: str | Path, envelope: SignedCanonicalManifest) -> bool:
    p = Path(manifest_path)
    try:
        manifest = CanonicalReleaseManifest.model_validate_json(p.read_text(encoding='utf-8'))
    except Exception:
        return False
    if not verify_canonical_manifest(manifest):
        return False
    if manifest.manifest_sha256 != envelope.canonical_manifest_sha256:
        return False
    if _public_key_fingerprint(envelope.signature.public_key_pem) != envelope.public_key_fingerprint_sha256:
        return False
    return verify_release(p, envelope.signature)


def write_signed_manifest(envelope: SignedCanonicalManifest, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(envelope.model_dump(mode='json'), indent=2, sort_keys=True), encoding='utf-8')
    return p
