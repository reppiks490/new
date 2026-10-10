# Model Inspection and Source-Preserving Import

**Goal:** Make imported and bundled models understandable, accurately
classified, and safely editable without corrupting their source structure.

**Architecture:** A read-only inspector produces a capability manifest; uploads
are normalized only into derived copies; Blender conversion runs in a bounded
worker; source, conversion recipe, logs, and hashes are stored separately.

**Tech stack:** FastAPI studio routes and scoped storage, Python inspection,
Blender Python, GLB/glTF validation, pytest, and Playwright.

**Spec:** [BEYOND_TRIPO_SPEC.md](../../BEYOND_TRIPO_SPEC.md)

**Global constraints:** Preserve source bytes, validate file type/size and paths,
keep imported assets private by default, do not publish user assets to a provider
without explicit action, and report unsupported/lost features precisely.

**Review focus:** Does inspection match Blender/glTF reopen results? Are shape
keys, UVs, materials, images, skeletons, weights, clips, and attachments
preserved where claimed? Are errors actionable and non-destructive?

## Task 1: Capability manifest for imported assets

**Files/interfaces:** New `app/studio/asset_inspector.py`, manifest models,
scoped `/api/studio/assets/{id}/capabilities` route in `app/studio/router.py`,
and tests in `tests/test_asset_inspector.py`.

- Write failing tests against representative static, skinned, morph-bearing,
  animated, malformed, and oversized GLB/GLTF fixtures.
- Inspect object/mesh and triangle counts, materials/textures, UV sets,
  skeletons/weights, shape targets/names, animation clips, coordinate scale,
  and parser warnings. State unavailable fields as unknown rather than zero.
- Compare reports with an independent library/Blender inspection for checked-in
  small fixtures. Do not add user Dropbox assets to distributable test data
  unless their licensing is verified.
- Verify upload, retrieval, and capability endpoints preserve confinement and
  reject invalid IDs.
- Commit: `feat: inspect imported model capabilities`.

## Task 2: Blender project ingest and conversion report

**Files/interfaces:** Worker task schema and conversion module under
`app/studio/processing/`, persisted jobs in `app/studio/storage.py`, job routes
in `app/studio/router.py`, and Blender live tests.

- Write failing Blender integration tests for a small fixture containing
  multiple meshes, shape keys, UVs, materials, vertex groups, a weighted rig,
  and one animation; test both successful and rejected conversions.
- Implement a background, resource-bounded `.blend` inspection/export job with
  per-data-class preservation report, source hash, output hash, version,
  timeout, and log. Export to a new derived asset. Do not call conversion
  lossless unless reopened output checks all requested structures and a
  representative pose.
- Verify under the supported Blender version, plus failure recovery when
  Blender is unavailable or crashes. Display accurate format-dependent
  limitations in the browser.
- Commit: `feat: add verified Blender project ingest jobs`.

## Task 3: Editability and source round-trip gate

**Files/interfaces:** source-specific capability/morph mapping entries, browser
model detail panel, and `tests/test_asset_roundtrip.py`.

- Add failing round-trip tests for the selected local `.blend` sources after
  license review: required morph names and deltas, UV/material assignment,
  armature weights, representative pose, and export/reopen parity.
- Implement mappings only for the properties that survive the verified route;
  preserve original `.blend` beside the derivative. Unsupported or lossy paths
  are clearly unavailable, not hidden.
- Verify key body morphs independently against the precision-editing plan's
  protected-region tests before exposing them as safe controls.
- Commit: `feat: expose only round-trip-verified model controls`.
