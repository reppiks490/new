# Dropbox model import checkpoint — 2026-10-09

The user resumed work and requested all Dropbox builds, prioritizing both Street
Fighter models. This supersedes the earlier pause. This pass is bounded to source
import and verification because the user asked to conserve usage.

## Saved sources and library

All eight downloads completed and passed byte count, Dropbox content hash, and
SHA-256 checks. Originals are retained unchanged in
`workspace/imported_models/sources/`. The download receipt is
`workspace/imported_models/download-receipt.json`. These files remain private,
ignored workspace data; they are not bundled into a public deployment or Git.

Five self-contained GLBs are registered in `workspace/studio/`. Registration
copies original bytes, uses a content-derived ID, preserves attribution metadata,
and rejects external resources and invalid binary ranges. Repeat imports dedupe.
The clothed Command Grab source was later converted and registered, bringing the
library to six models.

| Library model | Triangles | Embedded images | Browser verification |
| --- | ---: | ---: | --- |
| Street Fighter — Cammy T-pose | 2,000,000 | 2 (8K) | Loaded and project saved |
| Street Fighter — Cosplay | 401,989 | 3 (4K) | Loaded, project saved/reopened, GLB exported |
| Pomni — source model | 120,826 | 29 | Structure checked; visual review pending |
| Pomni — T-pose | 2,000,000 | 1 | Structure checked; visual review pending |
| Frozen Queen — source model | 493,953 | 3 | Structure checked; visual review pending |
| Command Grab — clothed, rigged character | 1,271,016 | 4 | Loaded, 12 source targets, project reopened and exported |

**All five GLBs have zero skins, animation clips, and morph targets.** Their
appearance is not evidence of editable topology, rigging, or body controls.
The editor reports the absence of source targets. None needs Draco, Meshopt,
or Basis decoders. Embedded credits are retained; licensing remains unverified.

## Implementation

- `app/studio/model_library.py`: private metadata inventory and lossless local
  registration; CLI in `scripts/register_studio_models.py`.
- Authenticated `/api/studio/models` and `/api/studio/models/{id}` endpoints;
  original files use the existing private asset endpoint.
- Models panel opens first. Inventory does not download models or the old base
  character. Both Street Fighter entries sort first.
- Downloads validate SHA-256 and enforce a 150 MiB limit. Imported materials,
  source morph targets, skinning and animation clips are retained when present.
- Model projects store source ID/hash and source morph values. Reopening verifies
  that the original source is unchanged. Local imports can be saved as GLB.
- Static scenes render on changes instead of continuously redrawing dense meshes
  while idle. Orbit damping remains supported. Animation playback is not added.

## Remaining source conversions

Blender inspection used factory startup and disabled embedded script execution.
No source `.blend` was overwritten. No conversion is claimed for these sources:

- **Command Grab.blend:** clothed character; 21 meshes, 912,723 base triangles,
  70-bone rig, eight expression keys, five packed images and no missing textures
  or animation. Hair alone accounts for about 806K triangles. Next candidate for
  conversion after checking shader compatibility and a reversible optimization.
- **Elegg_2.1.blend:** 95 meshes including rig widgets, 226,760 base triangles,
  three armatures, extensive morphs, complex toon materials. Fifty packed images;
  one missing water-droplet texture. Requires deliberate object selection and
  material conversion, not a blanket export.
- **HainekoV1.0.7z:** safely extracted with path/link and expansion checks. Its
  Blender file was written by 4.5.91; installed Blender 4.3.2 reports compatibility
  warnings, dependency cycles and invalid drivers. Contains adult anatomy
  components. Retained for technical inspection; not converted or previewed.

The Elegg review found a visible swimwear configuration, but none of the 296
visible body morphs has matching clothing deformation; applying them could break
the fit. Toon shaders also depend on Blender-specific nodes and one optional
skin texture is missing, so no visual-fidelity conversion is claimed. Haineko
has no verified fully clothed outfit configuration, so remains source-only.

Inventories and archive extraction records are in
`workspace/imported_models/reports/`. Inspection scripts are in `.studio-qa/`.

## Validation and access

`python -m pytest -q tests/test_studio_model_library.py tests/test_studio_backend.py`
passed **26 tests**. JavaScript syntax and `git diff --check` passed.

Playwright verified both Street Fighter loads and saves, source-target absence,
source-bound project reopening, Cosplay GLB export, no page errors, lazy startup,
and no horizontal document overflow at a 390-pixel viewport. This was headless
Chromium with software graphics, not an iPhone performance benchmark.

Local evidence is in `.studio-qa/model-library-browser-report.json` and
`.studio-qa/street-fighter-{1,2}.png`. The Cosplay export passes the GLB inspector
with the same 401,989 triangles, four meshes, one material, and three images.
That export also reloaded in the browser. A separate synthetic fixture verified
that one skin, one animation clip, and a morph value survive export/reimport.
The renderer produced zero additional frames during a 500 ms idle check and
redrew after a morph change. Evidence: `.studio-qa/model-engine-report.json`.
Command Grab conversion preserves its 70-bone skin and 12 facial targets. Its
body color graph was baked to a 2K texture; the Blender subsurface scattering
effect is not represented by glTF's core material model. The source gives the
character's fan artist credit, but no distribution license.

The local library has six registered models. A static package in
`/workspace/forma-site/dist` was built for the existing owner-only Sites project.
Sites limits the expanded deployment archive to 256 MiB, so the hosted catalog
contains Cammy, the Street Fighter cosplay model, and clothed Command Grab. The
other three GLBs remain in the full local library. Chromium loaded Command Grab
from a no-worker bundle and exposed all 12 facial targets. The private deployment
ID is `appgdep_6ac9cc437cb48191b448a9a1f43160dc`; check its status before claiming
the browser link is live.

Run the private studio from the repository root:

```sh
.venv/bin/uvicorn app.studio.server:app --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000/` on that machine. No public deployment or GitHub
push is claimed. The previous Sites staging copy is outdated. This checkpoint
does not complete rigging, sculpting, wardrobe fitting, production quality, or
live text/image generation.
