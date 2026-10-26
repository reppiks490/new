# Character3D / Cinematic Orchestrator — QA85 integration and CI evidence handoff

**Captured:** 2026-10-26 UTC. **Scope:** read-only inspection of GitHub PRs, commits, workflows, job steps/logs and existing acceptance runbooks. **Owner:** independent QA/coordination; this branch changes only this document. **No app, CI workflow, queue, router, media or helper-owned files changed.**

## Exact dependency / ownership snapshot

| PR | Frozen HEAD | Relationship / ownership | HEAD workflow evidence |
| --- | --- | --- | --- |
| [#8 master assembly](https://github.com/reppiks490/new/pull/8) | `9e8e7ea7f1a807cbd46b1e5dc702b958b6ffc796` | Draft; base `feat/cinematic-orchestrator-v1`; lead assembly work | [CI 39868799240](https://github.com/reppiks490/new/actions/runs/39868799240) SUCCESS |
| [#21 async assembly](https://github.com/reppiks490/new/pull/21) | `fd4e62e48846c013d74d1162012dd5539d0596d7` | Draft; based on #8; SQLite-backed queue, auth polling, local serialized CPU worker | [CI 39872877457](https://github.com/reppiks490/new/actions/runs/39872877457) SUCCESS |
| [#23 cache + real media](https://github.com/reppiks490/new/pull/23) | `c015ad1863e1201bb5dfa3c87ee79394a4f6f856` | Draft; separate helper candidate based on #8 | [CI 39870914298](https://github.com/reppiks490/new/actions/runs/39870914298) SUCCESS; [real-media 39870914258](https://github.com/reppiks490/new/actions/runs/39870914258) SUCCESS |
| [#40 lead integration](https://github.com/reppiks490/new/pull/40) | `05c59556d64a808dcc3a8ca96fae5e572c9e446d` | Draft; different base `codex/filmmaking-600s-capability-proof`; overlaps queue/service, web client and tests | [CI 39917307720](https://github.com/reppiks490/new/actions/runs/39917307720) SUCCESS; [real-media 39917307504](https://github.com/reppiks490/new/actions/runs/39917307504) SUCCESS |
| [#176 QA84 privacy](https://github.com/reppiks490/new/pull/176) | `e64163f67d32748c4248f87ac8590a5b8b3a2838` | Draft; stacked on #175, then prior QA chain; offline inspector only plus test/workflow | **32** PR-triggered runs: **16 SUCCESS, 16 CANCELLED**. [General CI 40326888795](https://github.com/reppiks490/new/actions/runs/40326888795) SUCCESS; [dedicated QA84 40326888738](https://github.com/reppiks490/new/actions/runs/40326888738) CANCELLED overall (3.12 success, 3.11 cancelled before test) |
| [#177 Helper 1 private delivery](https://github.com/reppiks490/new/pull/177) | `78ccca69ee5bf4de43725283cea765f1dcf6ed6f` | Draft; stacked on Helper 1 #174; modifies `app/video/router.py` and Helper-1-owned range test | **7** runs: **6 SUCCESS, 1 FAILURE**. [Range acceptance 40327104234](https://github.com/reppiks490/new/actions/runs/40327104234) FAILED in setup; no test executed |

**Important:** These are separate candidate HEADs. Green on #8, #21, #23 and #40 does **not** prove their combined code is green or merged. PR #176 is **not** fully green. PR #177's failing range workflow is **not** evidence that the proposed route fix fails a test.

The `feat/cinematic-orchestrator-v1` branch was verified identical to commit `ba492146af3bbdab0e9cf255a9ca8b56c395a889` at inspection. Comparing that base to #176 shows **186 commits ahead** on the stacked QA branch. This is a dependency/review-size warning, not a count of merged commits. No merge or deployment was performed.

## Reproduced CI infrastructure blocker on Helper 1 #177

Inspected both jobs of [run 40327104234](https://github.com/reppiks490/new/actions/runs/40327104234): Python 3.11 job `121586510513` and Python 3.12 job `121586511082`. Both failed at **"Verify FFmpeg FFprobe and libx264"** with exit code **124** while `apt-get` was downloading Ubuntu FFmpeg dependencies from `azure.archive.ubuntu.com`. The logs show slow package retrieval; all dependency installation and real-media pytest steps after that setup step were **skipped**. This is a *confirmed CI provisioning timeout*, not a confirmed application test failure. It does **not** verify the Helper 1 correction either.

**Recommended lead/Helper 1 next action:** reproduce the provisioning timeout in the exact workflow, then change **only the owning workflow** to use a reliable, provenance-verified FFmpeg/FFprobe installation strategy with explicit version/libx264 checks, bounded network retries and appropriate time budget. Re-run the same exact-HEAD genuine-media range tests on both Python versions. Avoid altering Helper 1 router/test files from another branch; do not infer the fix is correct until the tests actually execute.

## QA84 incomplete acceptance, not a clean matrix

[QA84 test-first RED 40326701002](https://github.com/reppiks490/new/actions/runs/40326701002) showed one expected strict-audit false acceptance and one clean control on Python 3.11 with genuine disposable FFmpeg H.264. The proposed inspector change checks immediate `dinf` children. On final #176 HEAD, the dedicated Python 3.12 job passed **2/2**, while Python 3.11 was cancelled during FFmpeg provisioning; general CI completed successfully on Python 3.11/3.12 and Docker. Other inherited workflows were cancelled. **Do not call the whole 32-workflow matrix green.**

**Recommended QA owner next action:** establish why so many workflows are cancelled (including concurrency and superseding commits), then obtain a complete dedicated 3.11/3.12 result on an unchanged SHA. Review the strict MP4 structural allowlist for false rejection of valid non-FFmpeg muxers; these targeted tests do not constitute comprehensive sanitization of arbitrary ISO-BMFF content.

## Integration and delivery gates — ordered, no automatic merge

1. **Lead ownership / graph:** inventory exact file conflicts and unique commits across #8, #21, #23, #40, the QA chain and Helper 1 #177 before selecting one frozen integration commit. #21 owns queue/server/storage; #23 owns cache service/media acceptance; #40 spans queue, service, browser and timing; Helper 1 owns private HTTP/range. Do not wholesale-merge all draft stacks or overwrite any agent branch.
2. **CI reliability:** triage #177 FFmpeg package-download timeout and #176 cancelled matrix independently. Avoid adding another always-triggered workflow to the already broad QA chain until existing acceptance can complete.
3. **Durable batch/master:** #21 documents SQLite atomic dedupe, oldest-first local CPU execution, 32 outstanding jobs, queued cancellation, and fail-closed startup handling of interrupted FFmpeg. It expressly supports **one local server instance** only; multi-worker startup fencing/leases remain unverified. Test crash/restart, stale revision and artifact publication on the *integrated* commit.
4. **Long-form timing and continuity:** #40 reports synthetic fractional-cut drift (four 2.525-second shots at 24 FPS yielding 244 instead of 242 frames) and a proposed frame-budget correction. Verify the integrated 600-second project against frame-accurate output, scene-boundary playback, source-image hashes and creative-edit freshness. Synthetic FFmpeg evidence does not prove visual identity/anatomy continuity.
5. **Private mobile delivery:** require authenticated, no-store, descriptor-pinned GET/HEAD/Range behavior after Helper 1 #177 is green; verify interrupted/truncated asset denial, reconnect/polling across network changes, no token in URL and physical mobile playback.
6. **Owner-machine readiness:** [600s acceptance runbook](https://github.com/reppiks490/new/blob/05c59556d64a808dcc3a8ca96fae5e572c9e446d/docs/FILMMAKING_ACCEPTANCE_600S.md) explicitly says real NVIDIA runtime/weights, model inference, owner-approved source image, ten-minute owner-PC render, physical iPhone verification and like-for-like WAN benchmark are **not proven**. Do not advertise synthetic FFmpeg, mock/browser tests or 4K rescaling as actual generated 4K film or native 120 FPS.

## Evidence boundary and handoff

This QA85 contribution is **a documentation-only, disjoint integration/CI blocker handoff**. No test-first defect correction was attempted because the highest-value verified blockers involve another helper's owned CI workflow and the integration lead's combined-commit decision. No synthetic media was generated in QA85; earlier cited CI runs contain genuine synthetic FFmpeg evidence. No owner media/credentials, actual model inference, owner-PC/mobile verification, paid services, cloud generation, merge, deployment or ICARUS/automation changes were made. CI on this documentation-only branch, if any, must be reported separately; a docs-only check is not runtime acceptance.
