# Cinematic Orchestrator — Verification Ledger

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
