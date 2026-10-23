# Phone startup crash mitigation — 2026-10-23

The owner supplied iPhone in-app Safari screenshots showing the studio shell,
then “A problem repeatedly occurred”. HTTP 200 checks alone had incorrectly
been described as a working application; they do not prove browser stability.

## Evidence and scope

The deployed default branch was `b39c1ce8229dfb6340ac2fa210b97fc4f2eaac95`.
Its automatic fallback opened the character and decoded all wardrobe textures.
The local source images total approximately 140 MiB of decoded RGBA data,
excluding GPU copies/mipmaps, geometry, model JSON, and browser overhead.
This is a credible memory-pressure trigger, not a measured iOS crash trace.

`app/studio/web/browser-performance.js` selects a bounded profile for coarse
pointers or windows up to 760 CSS pixels. `app.js` defers both the base character
and saved-GLB reads until explicit selection. The saved file stays in IndexedDB;
**Models → Open saved default model** restores it on demand.

`avatar-assets.js` sequentially decodes textures and resamples their retained
images to at most 512 pixels on the long edge. Original downloads remain
unchanged. `engine.js` uses DPR 1, disables multisample antialiasing/shadows,
and avoids retaining the drawing buffer on this profile. Snapshot capture
already draws synchronously before capture. Larger fine-pointer browsers keep
their prior visual settings and automatic model restoration.

These choices trade phone texture detail for lower startup and GPU allocations.
They do not cap arbitrary imported GLB geometry/textures or prove every phone can
open a large model. Existing saved models, exports, and private worker endpoints
are unchanged. Do not deploy the unfinished cinematic branch to obtain this fix.

## Verification at publication

- `node --test tests/*.mjs`: **28 passed**, including five new profile/texture tests.
- Python studio, curves, backend and model-library suites with warnings as errors:
  **46 passed**.
- Real Chromium mobile emulation (390×844 CSS pixels, touch, DPR 3) against the
  built Pages output: startup requested **zero** human/wardrobe assets and made
  **zero** IndexedDB model reads. Actual render buffer width was 390, with
  `preserveDrawingBuffer: false`.
- Explicitly opening the base produced **116,048 triangles**, resampled 11 large
  textures within the 512-pixel bound, and produced no page errors during the
  check. Snapshot control also executed.
- Independent code review found no critical or important issues.

This is Chromium evidence, not an actual iPhone Safari pass or a complete
Python/Blender/Docker matrix. The owner's iPhone must retry the published build.

## Continuation and rollback

The request was to fix the live crash and provide a usable link. Changes are
limited to browser loading/rendering and these tests/docs; no new runtime
dependencies, API contracts, migrations, cinematic integration, or provider calls.
Current operating guidance is in the README. No separate agent-router/skill/wiki
layer exists or is introduced for this bounded fix.

If the page still crashes before selecting a model, inspect renderer creation
and WebKit context/memory telemetry. If it crashes only after importing a file,
inspect that file's decoded textures/geometry before relaxing startup limits.
Rollback should revert this isolated hotfix, not unrelated cinematic work.
Revisit this note when device-profile detection, the asset loader, saved-model
startup, or renderer/snapshot behavior changes.
