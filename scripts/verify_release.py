from __future__ import annotations
import argparse, json
from pathlib import Path
from app.security.release_signing import ReleaseSignature, verify_release

p=argparse.ArgumentParser(); p.add_argument('artifact'); p.add_argument('signature_json'); args=p.parse_args()
env=ReleaseSignature.model_validate(json.loads(Path(args.signature_json).read_text()))
ok=verify_release(args.artifact,env)
print('VALID' if ok else 'INVALID')
raise SystemExit(0 if ok else 2)
