#!/usr/bin/env bash
# Downloads the CC0 MakeHuman assets the character builder uses
# (blender_scripts/makehuman_character.py): the base mesh and the young-adult
# race/gender macro targets. All were released CC0 in September 2020 (see the
# header of each file). Usage: scripts/fetch_makehuman_assets.sh [DEST_DIR]
set -euo pipefail
dest="${1:-assets/makehuman}"
raw="https://raw.githubusercontent.com/makehumancommunity/makehuman/master/makehuman/data"
mkdir -p "$dest"
curl -sfL -o "$dest/base.obj" "$raw/3dobjs/base.obj"
for race in caucasian african asian; do
  for g in male female; do
    curl -sfL -o "$dest/$race-$g-young.target" "$raw/targets/macrodetails/$race-$g-young.target"
  done
done
grep -q "released as CC0" "$dest/base.obj"
echo "MakeHuman CC0 assets in $dest"
