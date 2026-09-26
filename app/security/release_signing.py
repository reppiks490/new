from __future__ import annotations
import base64, hashlib, json, time
from pathlib import Path
from pydantic import BaseModel
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

class ReleaseSignature(BaseModel):
    algorithm: str = 'Ed25519'
    key_id: str
    artifact_name: str
    size_bytes: int
    sha256: str
    signed_at_unix: int
    signature_b64: str
    public_key_pem: str


def generate_ed25519_keypair() -> tuple[bytes,bytes]:
    private=Ed25519PrivateKey.generate(); public=private.public_key()
    priv=private.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
    pub=public.public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
    return priv,pub


def _payload(path: Path, key_id: str, signed_at: int) -> tuple[bytes,dict]:
    data=path.read_bytes(); meta={'artifact_name':path.name,'size_bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'key_id':key_id,'signed_at_unix':signed_at}
    return json.dumps(meta,separators=(',',':'),sort_keys=True).encode(),meta


def sign_release(path: str | Path, private_key_pem: bytes, *, key_id: str='release', signed_at: int|None=None) -> ReleaseSignature:
    p=Path(path); ts=int(time.time() if signed_at is None else signed_at); payload,meta=_payload(p,key_id,ts)
    key=serialization.load_pem_private_key(private_key_pem,password=None)
    if not isinstance(key,Ed25519PrivateKey): raise ValueError('private key must be Ed25519')
    sig=key.sign(payload); pub=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return ReleaseSignature(algorithm='Ed25519',signature_b64=base64.b64encode(sig).decode(),public_key_pem=pub,**meta)


def verify_release(path: str | Path, envelope: ReleaseSignature) -> bool:
    p=Path(path); payload,meta=_payload(p,envelope.key_id,envelope.signed_at_unix)
    if meta['artifact_name']!=envelope.artifact_name or meta['size_bytes']!=envelope.size_bytes or meta['sha256']!=envelope.sha256: return False
    try:
        key=serialization.load_pem_public_key(envelope.public_key_pem.encode())
        if not isinstance(key,Ed25519PublicKey): return False
        key.verify(base64.b64decode(envelope.signature_b64),payload); return True
    except Exception: return False
