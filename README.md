# Character3D Masterbuild v1.2

Local-first, prompt-driven high-fidelity 3D character production framework with provider routing across Tripo3D, Meshy, and Hi3D/Hitem3D plus a canonical Blender/USD finishing pipeline.

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
