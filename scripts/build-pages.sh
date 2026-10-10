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
import re
p=Path('dist/index.html')
s=p.read_text().replace('href="/"', 'href="./"')
version=os.environ.get('GITHUB_SHA','development')[:12]
for module in Path('dist/studio').rglob('*.js'):
    text=module.read_text()
    text=re.sub(r"(['\"])(\.{1,2}/[^'\"]+\.js)(?:\?[^'\"]*)?\1", lambda m: f'{m.group(1)}{m.group(2)}?v={version}{m.group(1)}', text)
    module.write_text(text)
for asset in ('./studio/style.css', './studio/vendor/three.module.js', './studio/app.js'):
    s=s.replace(asset+'"', asset+'?v='+version+'"')
p.write_text(s)
PY
