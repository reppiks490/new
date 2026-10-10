# Paused at the user's request — 2026-10-09

**Resumed later on 2026-10-09 at the user's request.** See
[Dropbox model checkpoint](DROPBOX_MODEL_CHECKPOINT_2026-10-09.md) for the current
source imports, verification, and next work. The text below is the earlier pause.

The user rejected the visual quality and explicitly asked to pause and save.
This checkpoint is unfinished work, not an accepted design, release, or claim
that the supplied reference quality has been reached. Do not resume feature
work or publish until the user asks to continue.

## Saved implementation

- Branch: `codex/browser-studio-customization` in `/workspace/3d-builder`.
- Standalone FastAPI studio (`app.studio.server:app`) and Three.js browser
  editor; body targets, project save/open, static GLB import/export, local
  terrain, and provider job integration.
- MakeHuman CC0 body data and authored targets; 242 controls. The 360 wardrobe
  entries are procedural surface recipes, not 360 finished authored outfits.
- Seven additional authored assets: two hairstyles, two outfits, eyelashes,
  and two footwear meshes; female/male skin color textures. Their older source
  declares AGPL-3.0-or-later. The actual license, notices, source archive, hashes,
  and conversion script are retained. Do not call these finish assets CC0.
- Browser helper-vertex fitting, source UVs, shared textures, body visibility
  masks, and material-specific shading.
- Latest, unreviewed additions: one-step Loop surface subdivision preserving
  corner UVs, procedural iris texture, studio environment reflections, shoes,
  and floor placement updates.
- Backend fixes written for job import failure, exception persistence, atomic
  capacity checks, SQLite closure, recovery beyond the latest 100 records,
  executor submission failure, credential redaction, and transport cleanup.
- Technical analysis of the supplied reference images is saved in
  `REFERENCE_QUALITY_ANALYSIS.md` and `VISUAL_REFERENCE_MEMORY.md`. The actual
  attached images were not copied or saved to personal cross-chat memory.

## Verification and defects at the stop

- JavaScript syntax and Python compilation checked at this checkpoint. This
  is not equivalent to successful end-to-end tests or visual acceptance.
- A browser run after the first five authored assets loaded successfully with
  no page errors. Screenshots remain locally at `.studio-qa/finish-full.png`
  and `.studio-qa/finish-portrait.png`; these PRECEDE the last subdivision,
  iris, environment and footwear changes.
- Earlier targeted curve tests passed (6). No completed result was received
  for the current full studio/backend regression run. Re-run after resuming.
- Latest renderer changes and GLB round-trip with all textures/assets are
  unverified. Inspect close portrait, front/side/back, body edits, and mobile.
- The face, hair, and overall art direction still fall short of the user's
  references. Stock assets and renderer changes do not establish finished
  sculpting, groom quality, realistic skin, or a production character.
- The Python `character.py` export still uses the earlier body/surface-clothing
  implementation. Authored outfit/hair/shoes/textured export parity was NOT
  implemented. Browser export is the path intended to include its visible
  assets, but the newest round-trip needs verification.
- Project state gained `hair`, `shoes`, and `skinTexture`; recheck browser and
  worker saves together after a worker restart.
- Static character only: no rig/animation correctives, cloth simulation,
  finished collision handling, sculpt brushes, or completed large wardrobe.
- No live provider generation verified; no provider keys configured here.

## Browser access and next resumption

No deployment was completed or announced. A private Sites project was created
earlier but remains undeployed:
`appgprj_6ac740c5dc98819187ca1c4c7114f02b`.
The `/workspace/forma-browser` staging copy is OUTDATED. Do not deploy it.
Nothing was pushed to the original GitHub repository during this pass.

To resume locally:

```sh
cd /workspace/3d-builder
.venv/bin/uvicorn app.studio.server:app --host 127.0.0.1 --port 8000
```

The Playwright browser cache is `/workspace/browser-cache`. Local socket-based
tests and Chromium previously required network permission in this environment.
Source conversion is reproducible by extracting the bundled
`app/studio/web/data/quality-assets/source-assets.zip` and running
`scripts/build_studio_finish_assets.py` against that directory.

Next work, only if requested: inspect the final renderer state, resolve the
asset/export parity and fitting defects, then judge one fully clothed finished
character against the technical reference notes before expanding scope.
