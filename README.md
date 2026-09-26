# Character3D Masterbuild v1.3

Local-first, prompt-driven high-fidelity 3D character, scene, and world production framework with provider routing across Tripo3D, Meshy, and Hi3D/Hitem3D plus a canonical Blender/USD finishing pipeline.

## v1.0 milestone

v1.0 closes the largest trust gap from the earlier builds: **the system now distinguishes what is implemented/tested from what actually executed live**.

A canonical character release must carry successful live evidence for its required stages rather than relying on code presence, provider metadata, or mock tests. Synthetic and compiled-only stages remain useful for development but are explicitly non-releasable.

### New v1.0 controls

- Runtime readiness inspection for Blender, OpenUSD/`pxr`, and provider credential configuration.
- Execution evidence classified as `live`, `synthetic`, or `compiled_only`.
- Blender execution receipts containing command, manifest, stdout/stderr, worker-receipt, and timing digests.
- Canonical release evaluation requiring live provider ingest, candidate promotion, Blender processing, QA, and export by default.
- Deterministic canonical release manifests with artifact hashes and manifest SHA-256.
- Ed25519 signing that refuses non-releasable canonical manifests by default.
- Public-key fingerprinting and signed-manifest tamper verification.
- OpenUSD/UsdSkel reports now distinguish static validation from authoritative `pxr` validation and attempt computed joint-transform validation when supported.
- API surfaces for runtime readiness, canonical release evaluation, and canonical manifest compilation.

### Existing production stack retained

- Tripo/Meshy/Hi3D capability routing and gap filling.
- Provider polling/webhooks, secure asset ingest, host/redirect validation, SHA-256 provenance, and SQLite ledgers.
- Local geometry inspection, exact intersection detection, repair planning, identity-gated repair acceptance, and candidate promotion.
- 2K/4K/8K + UDIM planning, PBR semantic validation, displacement/curvature/thickness adapter contracts.
- Skin, eye, groom, rig, corrective, deformation, and multiview QA.
- Cycles quality profiles, multi-GPU scheduling, leases, retry-safe job claiming, and resumable execution.
- USD/UsdSkel-oriented interchange plus GLB/GLTF/FBX/OBJ validation.
- Tamper-evident provenance chains and Ed25519 release signing.

## Tests

v1.0 regression status before packaging: **96/96 tests passing with warnings treated as errors**.

## Packaging-environment execution status

The packaging environment does **not** contain Blender, OpenUSD `pxr` Python bindings, or configured Tripo/Meshy/Hi3D API credentials. Therefore this package does not claim a live provider generation, Blender bake/repair/export, or a live canonical character release. Those stages are implemented and testable, but live evidence must be produced on a properly configured workstation/worker before the canonical release gate will pass.

See `docs/V10_EXECUTION_TRUTH.md` for the v1.0 trust model.


## v1.1 net-new
- Geometry tier policy: preview <=100k, 2M interchange, hardware-budgeted nondestructive hero multires.
- Tripo H3.1 baseline delta documented in `docs/V11_GEOMETRY_REALISM_PLAN.md`.
- Runway capability audit executed: connection authenticated; image models available, but workspace currently has 0 credits, so no reference image generation was falsely claimed.
- Scite research connector was invoked but its monthly MCP quota is exhausted; no Scite findings are claimed.
- Regression: 99 tests passing with warnings as errors.


## v1.2 net-new
- Deterministic source/build fingerprints that ignore transient caches and filesystem mtimes.
- Separate runtime-environment snapshots so host metadata does not contaminate source identity.
- Immutable SQLite artifact lineage with SHA-256 parents, branches, active pointers, compare-and-swap updates, and audited rollback events.
- Hash-linked stage checkpoints committing inputs, outputs, configuration, status, and rollback safety.
- Rollback planning that enumerates invalidated downstream stages and blocks traversal across non-reversible stages.
- Deep GLB/glTF 2.0 structural validation: header/chunks, index references, skins, animations, buffers, images, extensions, and confined external URIs.
- Canonical release diffing across artifacts, execution evidence, blockers, and releasability.
- Deterministic cache-free source ZIP builder with normalized timestamps and file modes.
- Regression: **114 tests passing with warnings treated as errors**.

See `docs/V12_REPRODUCIBILITY_LINEAGE.md`.


## v1.3 net-new

Scenes and worlds join characters as first-class outputs, alongside deeper
mesh/render capability tracking. Every item below is implemented and has
passing tests in this package; see `docs/V13_WORLDS_AND_RENDERING.md` for
scope notes on what remains intentionally unbuilt and why.

- **Scene/world composition**: `SceneSpec`/`SceneAssetInstance` data model.
  Scenes compose already-canonical, already-policy-gated character/prop
  assets by SHA-256 reference — scene assembly is a placement concern, not a
  new generation surface. Hardware-aware combined-scene triangle budgeting
  and deterministic scene-manifest hashing.
- **Animation clips**: `AnimationClip`/`AnimationTrack`/`Keyframe` model with
  monotonic-keyframe-time validation, morph-target tracks, and unknown-
  joint/empty-track QA against a bound rig's known joints.
- **Centralized content filtering**: prompt-safety patterns for character
  and scene prompts live in one shared module. Two categories — sexual
  content involving minors, and non-consensual sexual content — are
  unconditional hard blocks, independent of mode, tier, or any other flag.
- **Multi-asset scene export**: real per-instance meshes assembled into one
  multi-node GLB at their declared transforms, then re-opened and verified
  (every declared instance present, correct transform, no silent extras).
- **Procedural terrain**: deterministic, seeded diamond-square fractal
  heightmaps → real triangle meshes, no external model/network dependency.
- **Biome/region composition**: deterministic elevation + slope
  classification (water/beach/plains/forest/rock/mountain/snow) with real
  per-vertex mesh coloring, not a separate unused label grid.
- **Seamless world tiling with streaming/LOD**: one master heightmap sliced
  into tiles with exact shared-edge continuity (not approximated), LOD via
  exact stride subsampling, and a distance-based streaming manager with
  cache eviction. Wired into real scene export: visible tiles become real
  files with real SHA-256 provenance in a validated combined scene.
- **Advanced body-proportion morphing**: continuous per-vertex-weighted
  regional scaling about a pivot (not crude global/binary scaling) across
  17 proportion sliders (height, limb length/thickness, waist, hips, bust,
  glutes, muscularity, body fat, and more).
- **Provider capability research**: Tripo's 7-type creature auto-rig
  taxonomy and pre-flight Rig Check endpoint, Meshy's Smart Topology
  defaults, and Hi3D specialty-mode request builders (portrait/relief/
  multicolor/print-split) — each recorded with its actual confidence level
  and `last_reviewed` date, not presented uniformly.
- **Meshy preview→refine pipeline driver**: end-to-end two-phase task-chain
  execution (submit, poll, submit-dependent-task, poll), short-circuiting
  cleanly on either phase's failure.
- **Local image→prompt-hints analysis**: dominant palette, brightness/
  contrast, and structural edge density from real pixel computation —
  explicitly not a fabricated natural-language captioner, which would need
  a vision-language model this project doesn't have.
- **8K bake-output verification**: real file existence/resolution/hash
  checks against a bake contract, catching the case where a Blender
  worker's receipt claims success but a file is missing, truncated, or
  undersized — closed for single-tile contracts; multi-tile receipt
  verification remains an open, explicitly-flagged limitation.
- **Exceeding-8K render output**: HD/2K/4K/8K/16K output-resolution tiers,
  hardware-fit checking for render buffers, and real verification that a
  rendered file's actual dimensions meet the request — proven against a
  genuine 15360×8640 file, not a stub.
- **Exact polygon topology analysis**: triangle/quad/n-gon counts and true
  fan-triangulation effective-triangle-count for OBJ (GLB has no native
  quad primitive mode per the glTF 2.0 spec, so this is correctly scoped to
  the format that actually preserves polygon structure).
- Regression: **235 tests passing with warnings treated as errors**.

See `docs/V13_WORLDS_AND_RENDERING.md`.
