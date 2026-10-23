# Cinematic Orchestrator — Verification Ledger

## Stopping checkpoint — 2026-10-23

Request: resume the selected 3D repo, then find a stopping point and provide an immediately usable link. Actor: Codex. Base: `ba492146af3bbdab0e9cf255a9ca8b56c395a889`; isolated branch: `codex/cinematic-launcher-privacy-lifecycle`.

The existing browser studio is reachable at <https://reppiks490.github.io/new/> (HTTP 200 checked at this checkpoint). That deployment is the default-branch 3D studio, not this cinematic branch. Cinematic generation additionally requires the private worker; this checkpoint does not deploy or claim a playable completed film.

### Bounded change and knowledge delta

- Code: `app/studio/web/cinematic-launcher.js` and `app/studio/web/cinematic-studio.js`; regression: `tests/test_cinematic_launcher.mjs`.
- Documentation, decision context, and continuation memory stay here in the existing ledger; no new dependencies, schema, provider, API, deployment, or separate rule/skill/router layer is introduced.
- Assumption: the selected cinematic workstream remains the intended scope; preserve separately developed assembly/QA draft PRs rather than merging their overlapping implementations.
- Before: delayed startup/project/poll/media responses could reopen private content after exit or hide; cinematic previews ignored blur preferences. Now session checks and aborts discard obsolete responses, hidden renders remain neutral, and preview blobs are revoked on hide/exit. Restore reloads previews and reconnects polling; switching jobs supersedes the old poll.
- Why: cancelling a fetch alone does not protect against a response already resolved or a later body decode. Both cancellation and state/visibility checks are required. Hiding does not cancel server rendering or roll back writes already accepted by the worker.

### Observed verification and remaining gates

- Six original regression tests failed before the fix and passed afterward. Review found a shot-switch polling race; its added regression also failed before correction.
- `node --test tests/test_cinematic_launcher.mjs tests/test_cinematic_ui.mjs`: **22 passed**, including 13 new launcher regressions. The lightweight DOM harness verifies control flow and markup, not Safari layout or hardware playback.
- Full Node suite retains the pre-existing `tests/test_video_privacy.mjs` failure: its shell assertion expects an eager video script although the shell loads it through the cinematic launcher. The assertion is left intact for reconciliation with the separate QA branch.
- Full Python verification was started with warnings as errors but interrupted at the user's stopping request; failures had already appeared. This is not a passing full-suite result. The original branch's missing master-assembly implementation remains separate work.
- Docker build was attempted and failed while fetching build dependencies because the container could not verify this environment's proxy certificate. No Docker health or full GitHub matrix success is claimed.
- Independent code review identified the polling handoff race, now covered by the shot-switch regression. Actual private iPhone/worker behavior, full Python 3.11/3.12/Node/Docker CI, and assembly integration remain required before release.

Review this checkpoint when launcher navigation, privacy callbacks, job polling, or the deployment branch changes. To continue, run the focused command above, reconcile the separate master-assembly work, and obtain fresh full-matrix evidence before deploying cinematic changes.

---

Branch: `feat/cinematic-orchestrator-v1`
Spec: `docs/superpowers/specs/2026-10-22-cinematic-orchestrator-design.md`
Plan: `docs/superpowers/plans/2026-10-22-cinematic-orchestrator-v1.md`

This file is the durable implementation/verification ledger for the long-form filmmaking build. It exists so the state of the project does not depend on chat history.

## Quality policy

- No completion claim without fresh executable evidence.
- New behavior is developed RED -> GREEN.
- Delivery targets (for example 2160p/120 FPS) are never described as native generation capability unless the selected engine actually supports them.
- No paid API, CUDA runtime, external LLM, or FFmpeg dependency is required for orchestration unit tests.
- Existing quick image-to-video behavior must remain backward compatible.
- Final sign-off requires the complete GitHub CI matrix: Python 3.11, Python 3.12, Node browser tests, Docker build and `/health` smoke test.

## Task 1 — Cinematic domain + storage

### RED evidence

Commit: `a89e169fcd3b252e977f4974bb498f990401d4d0`
GitHub Actions run: `39822411924`
Python 3.12 job: `119976830434`

Observed result:

- `6 failed`
- `558 passed`
- `14 skipped`

Every failure was intentional and new:

- 5 failures: `ModuleNotFoundError: No module named 'app.video.cinematic_models'`
- 1 failure: `ValueError: Invalid video record kind` for `video_project`

No pre-existing test failed in the RED run.

### Implementation

- `app/video/cinematic_models.py`
- `app/video/storage.py` accepts `video_project`
- Blank `master_prompt` rejected at the model boundary.

Commits include:

- `515acfedaba47adfe2394ebe85b9e985ac4bf8c8` — cinematic domain models
- `a30cc56e818e7e019a0936960c9a36dd9b2faa00` — cinematic project storage kind
- `31e3f3b8a15dc1d5ee723bc20e4534fa66878060` — blank prompt hardening

### Full-CI status

Run `39822773650` was created for the Task 1 GREEN state. GitHub runners remained externally queued during implementation. This is a runner-availability condition, not accepted as proof of success. Final sign-off still requires a completed fresh full CI run.

## Task 2 — Deterministic long-prompt compiler

### RED definition

Test commit: `404b91c99f1063e0c8e654ebed71d000e29a5f97`

The tests pin:

- four explicit scene-marker syntaxes
- paragraph/sentence fallback decomposition
- automatic scene chunks <= 2,000 characters
- deterministic scene/shot IDs
- exact 600-second timeline budgeting
- exactly 60 shots for a 600-second target at a 10-second cap
- no shot exceeding engine duration caps
- blank prompt rejection
- iterative 100,000-character prompt compilation

### Implementation

Compiler commit: `3f671463047507cc033c6dba216925a374cf01ce`

Module: `app/video/cinematic_compiler.py`

Properties:

- zero-network / zero-LLM deterministic compiler
- explicit scene boundaries preserved
- automatic long-prose decomposition is iterative, not recursive
- stable SHA-256-derived opaque IDs
- duration arithmetic uses `Decimal` before conversion to stored floats
- global shot count is bounded by selected engine duration capability
- shot prompts use scene-local source material rather than blindly injecting the entire master prompt

### Local hermetic GREEN evidence

The exact committed model/compiler logic and the committed compiler test cases were copied into an isolated local Python harness and executed with pytest.

Result:

- `8 passed in 0.11s`
- Includes the 100,000-character stress case.
- Includes the exact 600-second / 60-shot case.
- Includes strict max-duration validation.

A separate unrelated spreadsheet-runtime warmup warning emitted by the host environment after pytest and did not affect the test process (`pytest` exit code 0).

## Runner-backlog execution ruling

GitHub Actions became queued for an extended period after the clean RED evidence was captured. To avoid halting implementation while preserving rigor:

1. Pure orchestration modules are allowed to advance using hermetic local RED/GREEN execution.
2. Every commit remains on the isolated feature branch.
3. Full GitHub CI is still mandatory before the branch can be called complete or merge-ready.
4. If final CI exposes any discrepancy, the discrepancy overrides local evidence and must be fixed before sign-off.

## Remaining implementation gates

- Task 3: atomic project persistence, optimistic revisions, continuity inheritance, reference resolution
- Task 4: capability-aware immutable render plans
- Task 5: cinematic API
- Task 6: shot-level queue integration
- Task 7: mobile Project Mode + privacy/browser tests
- Task 8: exact 600-second end-to-end acceptance fixture + runbook/setup docs
- final line-by-line spec audit
- final privacy/security review
- final full GitHub CI matrix
