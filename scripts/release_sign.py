#!/usr/bin/env python3
"""Local-only Ed25519 release signing utility.

Private keys are read/written on the local filesystem and are never embedded in the
release artifact. Keep private keys outside the packaged project/repository.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.security.release_signing import (
    ReleaseSignature,
    generate_ed25519_keypair,
    sign_release,
    verify_release,
)


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    k = sub.add_parser("keygen")
    k.add_argument("--private", required=True)
    k.add_argument("--public", required=True)

    s = sub.add_parser("sign")
    s.add_argument("artifact")
    s.add_argument("--private", required=True)
    s.add_argument("--key-id", default="release")
    s.add_argument("--out")

    v = sub.add_parser("verify")
    v.add_argument("artifact")
    v.add_argument("signature")

    a = p.parse_args()
    if a.cmd == "keygen":
        priv, pub = generate_ed25519_keypair()
        priv_path, pub_path = Path(a.private), Path(a.public)
        priv_path.parent.mkdir(parents=True, exist_ok=True)
        pub_path.parent.mkdir(parents=True, exist_ok=True)
        priv_path.write_bytes(priv)
        try:
            priv_path.chmod(0o600)
        except OSError:
            pass
        pub_path.write_bytes(pub)
        return 0

    if a.cmd == "sign":
        env = sign_release(a.artifact, Path(a.private).read_bytes(), key_id=a.key_id)
        out = Path(a.out) if a.out else Path(str(a.artifact) + ".sig.json")
        out.write_text(json.dumps(env.model_dump(mode="json"), indent=2, sort_keys=True), encoding="utf-8")
        print(out)
        return 0

    env = ReleaseSignature.model_validate_json(Path(a.signature).read_text(encoding="utf-8"))
    ok = verify_release(a.artifact, env)
    print("verified" if ok else "verification_failed")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
