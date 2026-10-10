# Precision Editing and Region Constraints

**Goal:** Make natural-language edits reviewable and safe, then apply them to
supported models with explicit protected-region guarantees.

**Architecture:** Parse prompts to typed edit intents; resolve anatomy through
an inspected per-model map of shape keys or versioned vertex masks; produce a
preview plan; apply an operation to a derived model version; persist the intent,
measured deltas, and undo link. Unsupported mappings block application.

**Tech stack:** Python/Pydantic edit schema and validation; existing Three.js
editor; Blender geometry worker for supported static meshes; pytest, Node tests,
and Playwright.

**Spec:** [BEYOND_TRIPO_SPEC.md](../../BEYOND_TRIPO_SPEC.md)

**Global constraints:** Follow the roadmap constraints. Never infer anatomy
solely from an object name; never invent an amount when omitted; use zero vertex
displacement for hard-protected regions; preserve clothing/attachments or report
that they are not bound; preserve original source bytes and allow rollback.

**Review focus:** Conjunction/negation parsing, semantic mapping evidence,
protected-region delta measurement, graceful blocking, undo, and same-camera
before/after quality.

## Task 1: Define and test typed edit intent

**Files/interfaces:** Add `app/studio/edit_intent.py`; Pydantic models for
operation, target regions, protected regions, numeric amount/unit, ambiguity,
and a parse report. Add focused tests under `tests/test_edit_intent.py`.

- Write failing tests first for “slim her waist without reducing glute and hip
  size”, explicit values/units, multiple targets, conjunctions, negation,
  synonyms, conflicting instructions, unsupported regions, and ambiguous
  amounts.
- Verify red against the current prompt behavior and record the failure.
- Implement a conservative parser that returns a typed plan. The key sentence
  must target waist, protect glutes and hips, and request amount review. Unknown
  or conflicting text must be blocked or surfaced as ambiguous, not guessed.
- Verify the focused tests pass and that no parser path defaults to 40%.
- Commit: `feat: parse safe structured model edit intents`.

## Task 2: Add model capability and anatomy mapping contracts

**Files/interfaces:** `app/studio/model_library.py`, new
`app/studio/capabilities.py`, mapping registry/schema, and
`tests/test_studio_model_library.py`.

- Add failing tests for static GLBs, GLBs with facial-only morphs, supported
  authored body morphs, malformed mappings, and missing anatomy metadata.
- Implement a report distinguishing supported local morph, mapped mask,
  provider-only, and unavailable. Record per-target vertex deltas and rig,
  material, image, UV, clip, scale, and conversion facts that are actually
  available from inspection.
- Use representative registered assets to check the report against their
  audited structures. Do not advertise a body control for facial-only targets.
- Verify tests and existing model-library suite.
- Commit: `feat: report per-model editing capabilities`.

## Task 3: Preview and apply constrained edits as reversible versions

**Files/interfaces:** new scoped routes in `app/studio/router.py`, persistence
in `app/studio/storage.py`, editor UI in `app/studio/web/app.js` and
`index.html`, geometry operations in a focused module, plus
`tests/test_studio_editing.py` and browser tests.

- Write failing API/browser tests for preview-before-apply, amount review,
  protected locks, rejected unsupported edits, operation history, undo/redo,
  save/reopen, and preservation of source hash.
- Implement preview reports containing affected objects/regions, chosen
  morph/mask, amount, protected-region maximum delta, warnings, and validation
  results. Require a user-set amount if the request omitted it.
- For approved edits, apply to a derived version. Enforce zero displacement on
  protected vertices; reject if smoothness, topology, clothing bindings, or
  export validation cannot be met. Keep same-camera before/after and region
  overlay visible before acceptance.
- Verify an exported and reopened model retains the edit and supported data;
  verify undo restores the prior model hash/geometry. Run the studio API suite
  and Playwright keyboard/mobile/desktop flows.
- Commit: `feat: apply reversible region-constrained model edits`.

## Task 4: Quality gate for supported body morphs

**Files/interfaces:** source-specific mappings and `tests/test_morph_quality.py`;
audited data may live under `app/studio/data/mappings/`.

- Write failing checks for every advertised breast, glute, hip, and waist
  target, both individually and in representative combinations.
- Measure affected and protected vertex sets, maximum displacement, smoothness,
  self-intersections, and body/clothing divergence against a documented
  tolerance. Do not assume correlated shape keys satisfy an independent lock.
- Mark targets incompatible with a particular protected constraint instead of
  presenting them as safe. Add correctives only with tested measurable results.
- Verify the key protected waist edit passes only on models whose mapping and
  deformation tests support it. Record known incompatibilities in capability
  reports and docs.
- Commit: `test: gate body morphs on constraint and quality checks`.
