from __future__ import annotations

import argparse
from pathlib import Path

from app.release.signed_manifest import sign_canonical_manifest, write_signed_manifest


def main() -> int:
    ap = argparse.ArgumentParser(description='Sign a verified, releasable Character3D canonical manifest with Ed25519.')
    ap.add_argument('--manifest', required=True)
    ap.add_argument('--private-key', required=True)
    ap.add_argument('--key-id', default='canonical-release')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    envelope = sign_canonical_manifest(args.manifest, Path(args.private_key).read_bytes(), key_id=args.key_id)
    write_signed_manifest(envelope, args.out)
    print(f'wrote {args.out} fingerprint={envelope.public_key_fingerprint_sha256}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
