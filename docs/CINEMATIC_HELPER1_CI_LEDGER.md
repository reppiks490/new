# Helper Bot 1 — CI, Acceptance Evidence, and Reliability

**Repository:** `reppiks490/new` (3D render)  
**Primary cinematic baseline:** `feat/cinematic-orchestrator-v1` at `ba492146af3bbdab0e9cf255a9ca8b56c395a889`  
**Separately-owned master assembly implementation:** `chatgpt/cinematic-master-assembly-20261022` at `2a0ea8fc3f02beae5b07f5bb06427749b390293f`  
**Isolated helper branch:** `chatgpt/cinematic-helper1-independent-qa-20261022`

## Ownership boundary

Helper Bot 1 owns build verification and test evidence: Python 3.11/3.12 matrix behavior, Python reports, Node privacy coverage, Docker health diagnostics, regression triage, and release gates. Other agents retain ownership of cinematic domain, batch assembly, production rendering, UI aesthetics, and private editor workflows. This branch does **not** modify production implementation, inference providers, paid accounts, or live rendering capabilities. Do not rebase or rewrite branches owned by other agents.

## Verified pre-change findings

- Baseline workflow `39827916297`: Python 3.12 **4 failed, 597 passed, 14 skipped**; Docker passed; Python 3.11 cancelled after the 3.12 failure.
- Master-assembly workflow `39858834852`: same four failures on Python 3.12; Docker passed; Python 3.11 cancelled.
- Failures are missing service-side implementation of `render_project_missing`, `project_render_status`, `MasterAssemblyNotReady`, and `_run_master_ffmpeg`. Treat them as **real, unresolved failures**, not a reason to hide or ignore tests.
- Branch `chatgpt/cinematic-master-assembly-20261022` already contains the new `BatchRenderRequest` and `AssembleMasterRequest` contracts; Helper Bot 1 deliberately does not duplicate that feature work.

## CI hardening delivered on this isolated branch

1. `strategy.fail-fast: false`: preserve full Python 3.11 and 3.12 outcomes, even when one test fails.
2. JUnit XML for each Python version, uploaded on a best-effort `always()` path. Failures remain failing.
3. Run independent Node browser privacy tests on the Python 3.11 leg even when the Python test suite is red (unless cancelled), making both signals visible.
4. Explicit job timeouts to avoid indefinitely stranded runner capacity.
5. Docker `/health` failures remain fatal, but container logs are now captured through an exit trap and stopped/removed reliably.

## Additive authorization regression suite

`tests/test_cinematic_auth_integration.py` is owned by this QA lane and is separate from the implementing agent's `cinematic_service` and `router` files. It checks all seven existing cinematic route patterns with missing or wrong bearer tokens, then checks that denied creates/updates do not alter persisted projects and a foreign-origin create is blocked despite having the correct owner bearer. No real video generation, external network, cloud API, or secret tokens are involved.

Do not mark these tests passing until an immutable GitHub CI run has executed the branch head.

## Browser regression exposed by the independent matrix

The new CI behavior was exercised by workflow **39859950662** at helper commit `90564c43618f57f8f81585bc54a4a2e050d3e372`:

- Python 3.11 executed to completion instead of being cancelled.
- The Python 3.11 and 3.12 pytest JUnit artifacts both uploaded successfully.
- Docker succeeded.
- The Node browser suite actually executed after a Python failure, exposing **43 passed, 1 failed**. The sole failure was a legacy assertion in `tests/test_video_privacy.mjs` expecting an eager `/studio/video-studio.js` script tag. The actual UI now uses `cinematic-launcher.js` to lazy-import `./video-studio.js`.
- The test now verifies the real launcher and dynamic module link. This is a test-contract correction, not a hidden failure exemption. **Fresh CI on the new head is still required** before claiming the browser suite green.

## Acceptance gates before combining branches

- [ ] Confirm the Python 3.11 leg executes to completion rather than being cancelled when Python 3.12 fails.
- [ ] Confirm Python 3.12 and 3.11 each upload a readable JUnit artifact when tests run.
- [ ] Confirm Node privacy tests execute and report independently after Python test failures.
- [ ] Confirm Docker `/health` passes; if it fails, preserve diagnostic output.
- [ ] Resolve the four actual cinematic master service failures on the implementation branch.
- [ ] Rerun full Python 3.11, Python 3.12, Node, and Docker checks on the proposed integrated head.
- [ ] Audit private-data leakage, revisional consistency, no unapproved paid inference, and no misrepresentation of delivery FPS/resolution as native model capability.
- [ ] Merge only after integration owner review; passing CI is required but not by itself sufficient for production-readiness claims.

All checks above are **evidence requirements**, not already-completed claims. CI workflow run links and the PR contain the current immutable evidence. 
