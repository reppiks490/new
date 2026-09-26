# v1.0 Execution Truth and Canonical Release

v1.0 introduces an explicit separation between **compiled/tested capability** and **live execution evidence**.

## Execution modes

Every critical production stage may be recorded as:

- `live`: the external/runtime tool actually executed and returned authoritative evidence.
- `synthetic`: deterministic fixtures, mocks, or fake transports were used.
- `compiled_only`: a contract/manifest/invocation was generated but not executed.

A release is not canonical merely because all code paths exist or all tests pass.

## Canonical release gate

By default the following stages must each have successful `live` evidence:

1. provider ingest
2. candidate promotion
3. Blender processing
4. QA
5. export

The composite production gate must also pass. Missing, failed, synthetic, or compiled-only evidence creates a release blocker.

## Canonical manifest

`app.release.canonical` creates a deterministic manifest (when supplied a fixed creation timestamp) containing:

- artifact hashes and sizes;
- execution evidence;
- required live stages;
- production-gate result;
- release blockers;
- a manifest SHA-256.

`verify_canonical_manifest()` recomputes the digest before signing or release.

## Signing

`app.release.signed_manifest` signs only a digest-valid canonical manifest. By default it refuses to sign a non-releasable manifest. Signing uses Ed25519 through the existing release-signing layer and records a SHA-256 fingerprint of the public key.

This signature proves integrity relative to the included public key. It does not by itself establish an externally trusted publisher identity unless that key is anchored by an external trust process.

## Blender evidence

`execute_blender_with_receipt()` records:

- invocation digest;
- manifest digest;
- process return code;
- stdout/stderr digests;
- duration;
- worker-receipt digest and terminal status.

A zero process exit is insufficient when a worker receipt is required. Missing or non-success worker receipts fail the stage.

## OpenUSD / UsdSkel

When `pxr` is available, validation is marked authoritative at the OpenUSD schema-parsing layer and attempts computed joint-transform validation. Without `pxr`, `.usda` can still receive static structural checks, but binary USD/USDC/USDZ validation cannot be called authoritative.

## Runtime readiness

`GET /v1/runtime/readiness` exposes only presence/configuration state, never credential values. It reports Blender, OpenUSD/pxr, and provider credential readiness along with blockers for live canonical execution.

At the v1.0 packaging environment, Blender, pxr, and provider credentials were unavailable, so no live provider generation, Blender repair/bake/export, or canonical live release is claimed.
