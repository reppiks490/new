# v0.9 Execution Chain

v0.9 turns the earlier QA primitives into a stricter production control path.

## Chain

`provider_submit -> provider_terminal -> asset_ingest -> candidate_promotion -> blender_repair -> bake -> qa -> export -> attest`

Every executed stage produces a SHA-256 receipt linked to the previous stage. A rejecting QA/acceptance result stops all downstream stages. Live provider submission is blocked until server-side credential readiness is present; API clients cannot self-declare authentication.

## Localized repair

The Blender worker consumes exact-intersection face IDs, duplicates the workflow into a separate candidate output, expands the face patch by a bounded adjacency radius, deletes the affected patch, fills/triangulates the hole, recalculates normals, and exports a candidate. The source asset is never overwritten.

A Blender success receipt alone is insufficient. `repair_acceptance` compares pre/post exact-intersection counts, mesh health, and region-weighted identity. The repaired candidate can be rejected even when Blender completes successfully.

## Retry-safe distributed work

`JobClaimStore` supplies durable token-guarded ownership with TTLs, heartbeats, retry backoff, terminal states, and monotonically increasing attempt counters. A second worker cannot take an unexpired claim.

## Groom animation QA

Animated grooms are sampled frame-by-frame. The aggregate report records failed frames, worst penetration ratio, and minimum clearance instead of reducing temporal collision behavior to one static pose.

## UsdSkel validation

The validator now distinguishes structural validity from production readiness. It checks SkelRoot/Skeleton bindings and, where available, authored joint arrays, bind transforms, rest transforms, animation-source relationships, joint-influence primvars, and malformed joint paths. The pxr/OpenUSD path is authoritative; USDA static parsing is explicitly a structural fallback.

## Bake adapters

NORMAL and AO map directly to Cycles selected-to-active passes. Displacement, curvature, and thickness require explicit source bindings/attributes and remain non-executable until those bindings are supplied. This prevents a planned channel from being reported as an executed bake.
