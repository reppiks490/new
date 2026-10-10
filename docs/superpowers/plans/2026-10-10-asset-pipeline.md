# Generation and Full Asset Pipeline

**Goal:** Provide usable prompt/image generation and verified segmentation,
texturing, rigging, animation, and stylization paths, locally where practical or
through named providers configured by the user.

**Architecture:** Capability registry describes actual local/provider
operations; typed jobs run via local worker or explicit adapter; every result is
validated and associated with provider/model/version, cost information, consent,
source/output hashes, and preservation report.

**Tech stack:** Existing provider catalog/router and Tripo/Meshy/Hi3D adapters,
studio jobs/storage, Blender worker, GLB/glTF validators, pytest, provider
contract tests, Playwright.

**Spec:** [BEYOND_TRIPO_SPEC.md](../../BEYOND_TRIPO_SPEC.md)

**Global constraints:** Do not misrepresent provider support, skip explicit
submission consent, silently transmit source data, or hide cost/credit details
when known. Keep unsupported tools unavailable. Preserve prior asset versions
and report any lost structure.

**Review focus:** Real end-to-end output rather than decorative UI; provider
contract/version correctness; no accidental paid requests; output quality and
round-trip integrity.

## Task 1: One capability and provider-truth registry

**Files/interfaces:** `app/providers/catalog.py`, `app/providers/router.py`,
studio capabilities endpoint and UI; provider tests.

- Write failing tests for each operation (text/image generation, segmentation,
  retopology, texture, rig, animation, stylization), including no credentials,
  missing model, and incompatible source.
- Reconcile declared provider profiles with implemented adapter methods and
  current API contracts. Publish statuses for local, configured, unavailable,
  and unverified. Include known costs/credits, data transmitted, and required
  consent when available.
- Verify no operation is advertised as live based only on key presence.
- Commit: `feat: report truthful asset pipeline capabilities`.

## Task 2: Prompt and image-to-3D jobs

**Files/interfaces:** existing generation adapters, scoped studio job router,
upload handling, `tests/test_generation_jobs.py`, provider contract tests.

- Write failing tests for text, image, and guided-prompt requests; upload bounds;
  consent; provider failure; poll/restart; result validation; duplicate request;
  and source-data transmission policy.
- Implement async jobs using verified adapters, validate output structure,
  persist provider operation IDs and outputs, and expose honest preview status.
  Require explicit submission after showing provider and known cost. Never put
  API secrets in browser state or logs.
- Verify with mocked contract tests and, only when configured, a clearly
  identified live smoke test. Keep unconfigured providers unavailable.
- Commit: `feat: run scoped prompt and image creation jobs`.

## Task 3: Segmentation and part selection

**Files/interfaces:** provider/local operation adapter, selection schema,
Three.js editor and tests.

- Write failing tests for multi-part labels, stable part IDs, coverage, source
  material/mesh references, unsupported provider outputs, and preservation.
- Implement segmentation only through an actual local model or configured
  provider. Bind selectable parts to source geometry and expose editable masks
  only after coverage/identity validation.
- Verify asset reopen and per-part isolation; otherwise report unavailable.
- Commit: `feat: add validated model segmentation`.

## Task 4: Texture, rigging, animation, and stylization

**Files/interfaces:** separate typed operations in `app/studio/processing/`,
provider adapters, Blender validation, and one focused test module per
operation.

- For each operation, write failing tests for prerequisites, supported input,
  output format, structure retention, and failure recovery before implementing.
- Implement texture generation/baking with UV validation; rigging with weight,
  hierarchy, pose, and joint checks; animation with clip/skeleton compatibility;
  stylization with named model/provider and measurable output checks. Keep
  operation-specific contracts rather than a generic success response.
- Verify output by reopening in Blender and the browser, inspecting a
  representative pose/material, and comparing manifests. Do not claim quality
  parity until fixed visual reviewers approve the comparison set.
- Commit separate focused changes for texture, rigging/animation, and
  stylization so each feature can be reviewed and reverted independently.

## Task 5: End-to-end quality and parity gate

**Files/interfaces:** `tests/e2e/`, fixed licensed test assets, visual review
protocol, and product capability documentation.

- Add regression cases from the approved spec: prompt-constrained edit,
  prompt/image creation, segmentation, retopology, texture, rig/pose, render,
  save/reopen, export/reopen.
- Run Python/JS, browser, Blender-live, and configured provider tests; report
  unavailable environment dependencies separately.
- Compare output against a fixed licensed reference set for anatomy, topology,
  surface quality, texture, lighting, and motion. Record failures and keep the
  feature gated until acceptance criteria pass.
- Commit: `test: add end-to-end asset quality gates`.
