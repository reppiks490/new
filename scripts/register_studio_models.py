#!/usr/bin/env python3
"""Register local user-provided GLB files in the private browser model library."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.studio.model_library import register_model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', type=Path, nargs='+', help='Self-contained GLB files (maximum 150 MiB each)')
    parser.add_argument('--name', help='Display name; only valid when registering one file')
    parser.add_argument('--source-credit', help='Source attribution, if known; does not verify a license')
    args = parser.parse_args()
    if args.name and len(args.files) != 1:
        parser.error('--name requires exactly one file')
    failed = False
    for source in args.files:
        try:
            result = register_model(source, name=args.name, source_credit=args.source_credit)
            print(json.dumps(result, ensure_ascii=False))
        except (OSError, ValueError) as exc:
            print(f'{source.name}: {exc}', file=sys.stderr)
            failed = True
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
