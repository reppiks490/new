# QA110 — Genuine synthetic 4K Character3D master acceptance (2026-10-27)

**Owner/scope:** Independent QA follow-up to QA109 draft #210 at frozen SHA `f22f6c654f71b0252661673ac317fdbdaa7e3a44`. Exactly three **new QA110-only paths**: this handoff, `tests/test_cinematic_4k_master_qa110.py`, and `.github/workflows/cinematic-4k-master-qa110.yml`. No existing production, queue, server, media, mobile, helper-owned paths or owner data modified. Draft, do not merge/deploy.

## Why this gap matters

QA109 proved that an isolated Linux FFmpeg toolchain can encode a disposable **160x90, 2-second** H.264 clip; QA93–103 proved **480p, 600-second** application-level assembly and private mobile delivery acceptance. Neither establishes that the **actual Character3D master assembler** successfully completes a 3840x2160 delivery profile. This opt-in gate directly tests that previously unverified combination.

The new test creates two disposable 320x180 FFmpeg color MP4s and a real 10-second Character3D project at `delivery_resolution=2160p`, 16:9 and 24fps. It persists two linked successful synthetic shot records, calls the actual `assemble_project_master`, and checks: 3840x2160 H.264/yuv420p, 240 frames, 10 seconds, ordered red-to-blue visual continuity, progressive `moov`-before-`mdat` indexing, SHA-256 agreement, full decode and verified cache reuse. This is **real synthetic FFmpeg application media**, not mock metadata or actual AI inference. The test is disabled in general CI and explicitly enabled only by the dedicated offline, nonroot, read-only-root container workflow. The runner has no network, bounded memory/PIDs and disposable tmpfs.

**This is an acceptance coverage addition, not a reproduced production defect.** A passing test will establish only a 10-second synthetic 4K Linux CI master. It cannot prove a 600-second 4K film, owner-PC/Windows/WSL2 performance, artistic continuity, GPU/model inference, soundtrack policy, actual iPhone playback, or a release-ready system. If it fails, inspect the exact CI log and classify the cause before proposing a production change.

## Current integration dependencies and release blockers

- Canonical `feat/cinematic-orchestrator-v1` vs QA109: **103 commits ahead, 0 behind, 109 differing paths** at the time of this QA110 branch creation. The accumulated QA stack is not a canonical integration result.
- Lead integration #40, master #8, async queue #21, cache/media #23 require one frozen combined integration SHA and strict CI on that exact SHA.
- Helper 1's cache-policy correction #171 and strict-media push gate #194 **diverge** from QA109; independent green checks are not combined-commit proof. Coordinate integration with their owner; do not edit their files here.
- QA99 #200: live worker can be invalidated by another process's startup recovery (strict xfail, not fixed).
- QA100 #201: source AAC is stripped from final master (explicit policy and implementation decision required).
- QA103 #204: unauthorized private-media denial lacks explicit `Cache-Control: no-store` (Helper 1 #171 owns proposed correction).
- Do not merge, deploy, buy services, generate cloud media, touch owner media/credentials, change ICARUS or ChatGPT automations.

## Verification contract

Report the final exact commit SHA and both general CI and dedicated QA110 workflow conclusions. Do not call a queued, skipped or xfailed test a passing genuine 4K acceptance. If a resource ceiling or runner limitation blocks 4K encoding, record it as an **environmental blocker**, not proof that owner hardware cannot render.
