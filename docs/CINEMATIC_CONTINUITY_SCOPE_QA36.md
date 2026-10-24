# QA36 — Cinematic continuity scope and implicit-reversion audit

**Status:** additive, read-only engineering handoff. **Base:** lead integration PR #40, commit `05c59556d64a808dcc3a8ca96fae5e572c9e446d`. No changes to production render plans, service, project schema, storage, async queue, or media.

## Exact behavior observed in the current code

`app/video/cinematic_service.py::resolve_effective_continuity` computes each shot's effective state as `merge_continuity(merge_continuity(project.continuity_bible, scene.continuity_patch), shot.continuity_patch)`. It does **not** fold prior shot patches into later shots. A scene patch similarly does **not** flow into the following scene unless that scene declares it. `app/video/cinematic_editing.py::preflight_editorial_timeline` uses the same scoped merge and reports field-name changes; this is consistent with current implementation, not a contradiction.

For example, if shot A explicitly changes wardrobe and shot B omits wardrobe, shot B resolves back to its scene/project baseline. If scene A declares weather and scene B omits it, scene B resolves back to the project bible. This may be the intended *per-shot override* model; it is **not** automatically a bug. It could nevertheless surprise an editor expecting physical/story state to persist across consecutive shots of a long film.

## Additive verification

`app/video/cinematic_continuity_scope_qa36.py` provides `audit_implicit_continuity_resets(project)`. It follows the existing resolver and reports only project/scene/shot identifiers, field names, boundary type and advisory count. It never returns prompt, wardrobe, notes, character values, file paths, media, or credentials. It does not mutate project state or affect jobs. Findings are **potential** implicit resets, not judgments about narrative correctness.

`tests/test_cinematic_continuity_scope_qa36.py` exercises:
- Shot-scope fallback and agreement with editorial timeline field-name diagnostics.
- Scene-boundary fallback.
- Explicit shot and scene overrides excluded from implicit-reset warnings.
- Freeform note fallback without leaking synthetic private values.
- No false positive for unchanged continuity, and no project mutation.

These are hermetic model/service tests: **no FFmpeg**, media encoding, owner data, local GPU, model inference, owner-PC 600-second render, or physical phone playback. Exact-head CI must be checked independently before declaring the branch green.

## Lead/owner decision required

Choose and document one policy before changing any production behavior:

1. **Scoped overrides (current):** scene/shot patches are local. Expose a UI/editorial warning when a field silently falls back, or explicitly label patches as nonpersistent.
2. **Carry-forward state:** a shot/scene patch updates downstream continuity until explicitly overridden. This is a **behavioral migration**, not a one-line correction; define scene-boundary resets, explicit clearing, note merging, stable frame-order evaluation, and how project revisions represent effective state.

Any policy change must update `resolve_effective_continuity`, editorial preflight, render-intent provenance digests, stale-shot invalidation, existing project migration, cache eligibility and queue publication together. Preserve private diagnostics and revision/CAS behavior. Test at least two scenes, many-shot long-form sequences, explicit overrides and intentional discontinuities. Do not silently reinterpret already rendered projects.

## Coordination and ownership

Lead #40 owns production continuity and render provenance. Master #8, async #21 and cache/media #23 must be reviewed as dependencies; #21/#23 diverge from #40 and should not be blindly merged. This QA36 branch owns only the new audit helper, tests and this document. No merge/deployment/cloud generation/paid service/owner-media transfer is authorized.
