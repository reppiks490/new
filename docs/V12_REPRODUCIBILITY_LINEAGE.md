# v1.2 Reproducibility, Lineage, Rollback, and Export Integrity

v1.2 hardens the post-v1.0 production chain around four failure modes that become increasingly important as models, bakes, and exports are revised repeatedly.

## Deterministic build fingerprints

`app.release.reproducibility` inventories project files in deterministic relative-path order, excludes transient cache/VCS directories, and hashes each file plus a canonical metadata payload. File mtimes do not affect the source fingerprint. Runtime environment information is captured separately so source identity is not polluted by host-specific values.

## Immutable artifact lineage

`ArtifactLineageStore` stores immutable asset versions keyed by content SHA-256, with explicit parent hashes and branches. Rollback does not delete history or rewrite a past version. It changes only the active pointer and appends an audit event. Active-pointer updates support compare-and-swap to prevent one worker from rolling back over another worker's newer promotion.

## Hash-linked stage checkpoints

Each stage checkpoint commits input hashes, output hashes, configuration digest, status, rollback safety, and the previous checkpoint hash. The store verifies the chain before a rollback plan is trusted. A rollback plan enumerates exactly which later checkpoints/stages become invalid and blocks automatic rollback when the target or crossed stages are marked non-reversible.

## GLB / glTF structural validation

The v1.2 validator checks the GLB header/chunk structure or glTF JSON, glTF 2.0 asset version, array-reference bounds, skins/joints/inverse-bind references, animation sampler/channel references, texture/image references, external buffer/image presence, buffer lengths, extension declarations, and URI confinement. Absolute paths, parent-directory escapes, remote schemes, and missing external resources are release blockers.

This is intentionally separate from visual QA. A structurally valid glTF can still be visually or anatomically wrong, and visual quality cannot excuse a corrupted interchange package.
