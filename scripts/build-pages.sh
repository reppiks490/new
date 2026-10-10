#!/usr/bin/env bash
set -euo pipefail
rm -rf dist
mkdir -p dist/studio
cp -R app/studio/web/. dist/studio/
python - <<'PY'
from pathlib import Path
for p in Path('dist/studio').rglob('*'):
    if p.is_file() and p.suffix in {'.html', '.js', '.css'}:
        import re
        s=re.sub(r'(?<!/api)/studio/', './studio/', p.read_text())
        p.write_text(s)
PY
cp dist/studio/index.html dist/index.html
rm dist/studio/index.html
python - <<'PY'
from pathlib import Path
import os
p=Path('dist/index.html')
s=p.read_text().replace('href="/"', 'href="./"')
version=os.environ.get('GITHUB_SHA','development')[:12]
for asset in ('./studio/style.css', './studio/vendor/three.module.js', './studio/app.js'):
    s=s.replace(asset+'"', asset+'?v='+version+'"')
p.write_text(s)
PY
