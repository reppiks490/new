#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.release.source_package import build_deterministic_zip, write_source_release_manifest


def main() -> int:
    ap = argparse.ArgumentParser(description='Build deterministic Character3D source release ZIP.')
    ap.add_argument('--root', default='.')
    ap.add_argument('--version', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    root = Path(args.root).resolve()
    manifest_path = write_source_release_manifest(root, version=args.version)
    out = build_deterministic_zip(root, args.out)
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    print(json.dumps({
        'manifest': str(manifest_path),
        'zip': str(out),
        'sha256': digest,
        'size_bytes': out.stat().st_size,
    }, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
