#!/usr/bin/env bash
set -euo pipefail
rm -rf dist
mkdir -p dist/studio
cp -R app/studio/web/. dist/studio/
python - <<'PY'
from pathlib import Path
for p in Path('dist/studio').rglob('*'):
    if p.is_file() and p.suffix in {'.html', '.js', '.css'}:
        s=p.read_text().replace('/studio/', './studio/')
        p.write_text(s)
PY
cp dist/studio/index.html dist/index.html
rm dist/studio/index.html
