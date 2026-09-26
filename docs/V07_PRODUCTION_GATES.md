# v0.7 production gates

v0.7 moves the pipeline from measurement-only QA toward corrective and preservation-aware production control.

## Geometry repair

`app.qa.repair` compiles an explicit repair plan from measured mesh defects. The automatic local repair path is deliberately conservative: it removes degenerate faces, removes orphaned vertices, and repairs winding/normals when needed. Hole filling is opt-in because intentional anatomical/clothing openings must not be silently closed. Broad-phase self-intersection findings are never mislabeled as exact intersections; those remain gated for an exact Blender/BMesh or robust geometry-kernel pass.

Every repair emits before/after QA state plus source/output SHA-256 values so the operation is auditable and rejectable if quality regresses.

## Identity preservation

`app.qa.identity.compare_landmarks` performs shape comparison after removing translation, uniform scale, and rotation. Reflections are not accepted as equivalent. This is a character-shape continuity score, not biometric identification.

## Specialized hero QA

Skin, eyes, and grooms are evaluated independently. The QA models distinguish blockers from warnings so a missing cornea shell is not treated the same as a missing tearline, and an unbound groom is not treated the same as low guide density.

## Multiview consistency

Rendered-view comparison uses normalized structure and edge agreement. It is a deterministic appearance-consistency signal intended to complement, not replace, landmark/geometry identity scoring.

## Export validation

Common mesh exports are parsed locally with `trimesh` and checked for actual geometry and finite vertices. USD-family files are validated only when USD Python bindings are present; otherwise the report explicitly declares that the validator is unavailable and defers to Blender/USD tooling.

## GPU scheduling

The scheduler filters unhealthy or under-provisioned workers, enforces required capabilities, reserves VRAM headroom, incorporates queue depth, and can prefer an explicit backend such as OptiX.

## Local artifact attestation

The existing append-only provenance hash chain is now complemented by optional HMAC-SHA256 file attestations. HMAC provides shared-secret authenticity/integrity; it is not a public-key signature and is not represented as one.

## Blender production manifest

The manifest compiler joins Cycles quality profiles, UDIM bake policy, and export targets into a deterministic job document. The Blender-side worker records each executed stage. UDIM baking is intentionally reported as preflight-only until explicit high/low bake sources and material-node bindings are supplied.
