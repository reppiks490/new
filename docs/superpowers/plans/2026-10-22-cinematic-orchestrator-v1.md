# Cinematic Orchestrator v1 Implementation Plan

> REQUIRED EXECUTION: test-first, task-by-task, with full CI verification before completion claims.

**Goal:** Extend the existing private mobile video studio into a persistent long-form filmmaking system for 10-minute+ projects with deterministic prompt decomposition, multi-image references, continuity state, capability-aware shot plans, selective rendering, and an additive mobile project UI.

**Architecture:** Keep existing single-shot generation untouched. Add a project layer (`project -> scenes -> shots`) above the existing engine registry and render queue. A deterministic zero-cost compiler creates shot graphs; a service layer resolves revisions, continuity and references; immutable render plans separate native generation settings from requested delivery settings; the current queue renders one selected shot at a time.

**Spec:** `docs/superpowers/specs/2026-10-22-cinematic-orchestrator-design.md`

## Global constraints
- No paid API, CUDA, external LLM, or FFmpeg dependency for orchestration unit tests.
- Preserve existing `/api/video/generate`, jobs, images, privacy, and assets behavior.
- Master prompt max: 100,000 chars.
- Target duration: 10..28,800 seconds.
- Delivery FPS: 1..120; delivery resolution: 480p/720p/1080p/1440p/2160p.
- Delivery quality targets must never be misrepresented as native generation capability.
- References use validated opaque 32-char lowercase hex image IDs only.
- Project writes use optimistic revisions; stale writes return 409.
- Prompt/continuity text never enters filenames or neutral job labels.
- Shot duration is compiler-bounded to engine limits; no silent render-time truncation.

## Task 1 — Domain models and storage
Create `app/video/cinematic_models.py`; extend `app/video/storage.py` with `video_project`; add `tests/test_cinematic_models.py` covering prompt limit, duplicate IDs, positive durations, continuity merge, reference dedupe, and storage roundtrip.

## Task 2 — Deterministic long-prompt compiler
Create `app/video/cinematic_compiler.py` and `tests/test_cinematic_compiler.py`. Support explicit scene markers and paragraph/sentence fallback; deterministic IDs; exact duration budgeting; 600-second project fixture; never exceed engine max shot duration.

## Task 3 — Persistence/revisions/continuity
Create `app/video/cinematic_service.py` and `tests/test_cinematic_service.py`. Implement create/list/get/update, optimistic concurrency, continuity inheritance, ordered reference resolution, and local-asset validation.

## Task 4 — Capability-aware immutable render plans
In service tests prove 2160p/120 delivery intent negotiates to 1080p/60 when that is the engine maximum while preserving delivery targets. Plans contain only local shot text plus effective continuity, not the entire master prompt.

## Task 5 — API
Extend `app/video/router.py` and `tests/test_video_api.py` with project CRUD, compile, plan endpoints and exact 404/409/422 semantics while reusing existing auth/origin protection.

## Task 6 — Shot rendering
Map render plans to existing `VideoGenerationRequest`, submit via existing queue, correlate job ID back to shot metadata, and prove no private master prompt is duplicated into job summaries.

## Task 7 — Mobile Project Mode
Extend `app/studio/web/video-studio.js/.css`; add browser tests. Add project list/editor, scene timeline, shot inspector, references, compile/plan/render controls while preserving Quick Generate and privacy/quick-hide behavior.

## Task 8 — End-to-end acceptance and documentation
Add `tests/test_cinematic_acceptance.py` for an exact 600-second project, late-shot continuity/reference inheritance, selected-shot fake render, and old quick-generate regression. Update `docs/PRIVATE_VIDEO_STUDIO_RUNBOOK.md`, `docs/VIDEO_LOCAL_SETUP.md`, and add `docs/CINEMATIC_ORCHESTRATOR.md` with architecture, limits, recovery, phone workflow, and future adapters.

## Final aggressive review
1. Run full Python suite with warnings as errors on CI Python 3.11 and 3.12.
2. Run all Node browser tests.
3. Require Docker build/health CI success.
4. Re-read spec line by line against implementation and tests.
5. Inspect diff for privacy leaks, unsupported quality claims, stale revision races, duration arithmetic errors, and quick-generation regressions.
6. Fix every Critical/Important finding and re-run CI.
7. Do not merge; leave the validated branch documented and reviewable.
