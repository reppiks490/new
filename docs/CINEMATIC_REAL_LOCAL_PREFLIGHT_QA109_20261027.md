# QA109 — Real Linux local FFmpeg readiness / disposable encode acceptance (2026-10-27)

**Scope:** Independent QA-only follow-up to draft QA108 #209 at `a3d7072a28cbf7ea5e936d13e3f7e6d1d11746cf`. Three **new** QA109 paths only: this handoff, `tests/test_cinematic_real_local_preflight_qa109.py`, and `.github/workflows/cinematic-real-local-preflight-qa109.yml`. No production source, concurrent helper-owned paths, credentials, or media touched. Draft; do not auto-merge.

## Gap and evidence boundaries

QA105–108 verified the local preflight through mocked subprocess/encoder/disk cases, and QA108 separately checked FFmpeg metadata in a sandbox. Those results did **not** execute a real video encode under the exact preflight report on the same runner.

QA109 adds an opt-in acceptance gate in the existing isolated Debian FFmpeg image. It calls the **real** preflight against a disposable tmpfs workspace, asserts all four limited checks pass and the preflight creates no files, and independently encodes a **two-second synthetic blue H.264 MP4** with `libx264`. It checks 48 frames at 24 fps, 160x90, yuv420p, duration, SHA-256 and full FFmpeg decode. The container has no network, read-only root, nonroot user, bounded memory/pids and tmpfs; the test is skipped by default in ordinary CI unless `CINEMATIC_REAL_PREFLIGHT_QA109=1`.

**This is an acceptance coverage addition, not a reproduced pre-existing production defect.** The preflight remains read-only and its `release_ready` flag remains false. A passing CI run demonstrates the specific **Linux CI image** can encode a synthetic clip; it does not prove the owner's Windows/WSL2 FFmpeg installation, GPU availability, model inference, 600-second local performance, source-audio continuity, real footage privacy, or physical mobile playback. Existing QA94–104 separately cover genuine synthetic 600-second assembly/HTTP acceptance.

## Dependencies and remaining release blockers

- Lead integration PR #40 and canonical `feat/cinematic-orchestrator-v1` still need a frozen combined SHA and all relevant strict CI gates on **that** SHA.
- QA99 #200 confirms a live-worker multi-process recovery bug; the inherited strict xfail is not a correction.
- QA100 #201 establishes missing source AAC in assembled masters, pending explicit audio policy.
- QA103 #204 confirms missing explicit no-store on denied private HTTP requests; Helper 1 #171 proposes the fix, and #194 proposes strict-media push gating. Their independent CI is not combined integration proof.
- No deployment, merge, cloud generation, purchase, owner media access, automation, or ICARUS work is authorized here.

## Verification

Test/CI source commit and final HEAD, exact workflow run URL and result must be added to the PR discussion after GitHub Actions completes. A passing general CI alone is insufficient to claim this real-media gate passed.
