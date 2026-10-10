#!/usr/bin/env bash
set -euo pipefail
rm -rf dist
mkdir -p dist/studio
cp -R app/studio/web/. dist/studio/
python - <<'PY'
from pathlib import Path
p=Path('dist/studio/index.html')
s=p.read_text()
s=s.replace('href="/studio/', 'href="./')
s=s.replace('src="/studio/', 'src="./')
p.write_text(s)
PY
cp dist/studio/index.html dist/index.html
rm dist/studio/index.html
