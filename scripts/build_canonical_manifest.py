from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.release.canonical import artifact_from_path, compile_canonical_release_manifest, write_canonical_manifest
from app.workers.execution_evidence import ExecutionEvidence


def _artifact(value: str):
    if '=' not in value:
        raise argparse.ArgumentTypeError('artifact must be KIND=PATH')
    kind, path = value.split('=', 1)
    if not kind or not path:
        raise argparse.ArgumentTypeError('artifact must be KIND=PATH')
    return kind, path


def main() -> int:
    ap = argparse.ArgumentParser(description='Build a Character3D canonical release manifest from real artifact files and execution evidence.')
    ap.add_argument('--job-id', required=True)
    ap.add_argument('--artifact', action='append', type=_artifact, default=[], help='Repeatable KIND=PATH input')
    ap.add_argument('--evidence', required=True, help='JSON file containing an array of ExecutionEvidence objects')
    ap.add_argument('--production-gate-passed', action='store_true')
    ap.add_argument('--required-live-stage', action='append', default=[])
    ap.add_argument('--created-at-unix', type=int)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    artifacts = [artifact_from_path(path, kind=kind) for kind, path in args.artifact]
    evidence_data = json.loads(Path(args.evidence).read_text(encoding='utf-8'))
    evidence = [ExecutionEvidence.model_validate(x) for x in evidence_data]
    manifest = compile_canonical_release_manifest(
        args.job_id,
        artifacts,
        evidence,
        production_gate_passed=args.production_gate_passed,
        required_live_stages=args.required_live_stage or None,
        created_at_unix=args.created_at_unix,
    )
    write_canonical_manifest(manifest, args.out)
    print(json.dumps({'out': args.out, 'releasable': manifest.releasable, 'sha256': manifest.manifest_sha256, 'blockers': manifest.blockers}, indent=2))
    return 0 if manifest.releasable else 2


if __name__ == '__main__':
    raise SystemExit(main())
