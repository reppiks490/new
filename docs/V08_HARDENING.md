# v0.8 Hardening and Production Mechanics

v0.8 converts several previous QA placeholders into actionable production gates.

## Exact self-intersections
`app.qa.exact_intersections` performs triangle/triangle testing after AABB broad-phase rejection and ignores normal adjacent-face contact. Coplanar overlap is projected to 2D. Reports distinguish exact intersecting pairs from the older broad-phase candidate list. Repair remains conservative: small affected sets receive a localized patch-remesh plan; larger failures escalate to region/voxel remeshing in Blender or another robust geometry kernel. The lightweight Python layer never silently deletes intersecting geometry.

## Region-weighted identity
Landmarks can be grouped into high-value facial regions (eyes, nose, lips, jaw, ears, etc.) with independent weights. Alignment removes translation, uniform scale, and rotation while disallowing reflection. A global score can therefore no longer conceal a severe failure in a critical facial region.

## Rig and deformation QA
Skin-weight QA verifies normalized weights, influence budgets, negative weights, zero-weight vertices, and unknown bones. Pose deformation QA evaluates maximum edge stretch, volume preservation, and penetrations. Failed poses feed the corrective-morph planner, which emits non-destructive pose-space/RBF corrective targets.

## Groom collision QA
Sampled groom points are tested against watertight body meshes with deterministic ray-parity inside/outside classification. Root points are excluded by default because slight scalp embedding is normal. Non-watertight bodies are explicitly downgraded to a warning and should be re-tested inside Blender.

## High-to-low UDIM baking
`blender_scripts/high_low_udim_bake.py` is a real selected-to-active Cycles bake worker. It can execute NORMAL and AO channels to tiled EXR outputs. Displacement, curvature and thickness are not falsely marked complete without source-specific material/binding information. Extreme mode requires an explicit cage.

## UsdSkel
When OpenUSD Python bindings are installed, validation uses `pxr`. Without them, ASCII USDA receives a structural fallback check; binary USD/USDC/USDZ is deliberately marked unavailable rather than guessed.

## GPU leases and heartbeats
SQLite-backed worker leases prevent two jobs from believing they own the same GPU worker. Heartbeats extend leases, expired leases are reclaimable, and lease tokens are required for mutation/release.

## Release signatures
Release artifacts can now be signed with Ed25519. The signature envelope binds file name, byte length, SHA-256 digest, key ID and signing time. The private signing key is never bundled with the artifact.

## Integrated control plane
v0.8 now exposes worker-lease acquire/heartbeat/release/reclaim operations through the FastAPI control plane. The SQLite path is server configured with `CHARACTER3D_LEASE_DB`; clients cannot request arbitrary filesystem locations.

A composite production gate accepts independent named QA checks and preserves every domain's blockers/warnings. This allows topology, identity, rig, groom, texture, render, and export checks to block release independently without hiding the failure cause behind a single score.

## Bake orchestration and receipts
`app.workers.high_low_bake` serializes bake contracts, compiles a security-first Blender background invocation, parses the authoritative Blender receipt, and rejects a bake as complete when required channels such as NORMAL or AO were not actually executed.

## Local release signing CLI
`scripts/release_sign.py` provides key generation, signing, and verification for Ed25519 release envelopes. Private keys should live outside the source/package tree. The signed payload binds artifact name, size, SHA-256 digest, key ID, and signing time.
