# QA78 — allowed encoder metadata item privacy acceptance

**Status:** isolated draft / do not merge. Frozen parent: QA77 #165 at `83a8aceaf60a83a73c21195cf9464af224672482`. QA77 exact-final-head workflow checkpoint: 23 successes, 2 cancellations (QA75 and QA63); **not** 25/25 green.

## Test-first reproduced defect

Test-only head `21d85ffacc5d77197547c84e965dda9739a1a0de`, [QA78 regression run 40281181043](https://github.com/reppiks490/new/actions/runs/40281181043), **RED on Python 3.11 and 3.12**: 1 failed / 1 clean control passed on each. The failure was the intended strict-audit exit-code assertion (actual 0, expected 1), not a fixture/setup failure.

A disposable genuine FFmpeg H.264 MP4 had a synthetic private canary in a `priv` child nested under the otherwise allowed `moov/udta/meta/ilst/©too` encoder item, adjacent to the legitimate `data` child. FFprobe still reported H.264, 48 frames at 24 FPS, two seconds and no canary; full video decode and persisted temporary SQLite SHA passed; legacy decode-only passed. Strict offline attestation incorrectly succeeded. This is a local offline privacy-integrity acceptance gap, **not** evidence of remote exploitation or owner media exposure.

## Narrow correction

Commit `9b0ef6e0850821fb1df5393ff3e8155eaefb7686` adds a conservative immediate-child allowlist to the **opt-in read-only** offline completed-master inspector for `©too`: require exactly one `data` child, reject unknown siblings and duplicate `data` headers. It reuses bounded header-only parsing; no payload contents, paths, canaries or owner media are emitted. Legacy decode-only remains unchanged.

The test encodes/decodes genuine disposable FFmpeg H.264 media and verifies FFprobe, SQLite SHA and report counters. It does **not** establish model inference, actual owner footage, 600-second owner-PC rendering, 4K/120 FPS generation or physical iPhone playback. This conservative contract may reject otherwise valid third-party muxer metadata. The `data` payload's content is not comprehensively sanitized, nor are all possible MP4 nested boxes.

## Ownership / merge gates

- Dependencies: #8 master assembly, #21 async durable queue, #23 cache/media, #40 lead integration, #165 QA77 parent.
- Concurrent Helper 1 #164 owns authenticated private-media streaming and snapshot concurrency. This PR changes no router, production worker, queue, cache, mobile UI or Helper 1 file.
- Require exact **final-head** Python 3.11/3.12 dedicated genuine-media workflow, general CI and inherited compatibility checks. Check cancellations as non-success. Keep draft/unmerged for lead review.
- No cloud generation, purchases, deployment, force-push, owner media/credentials, ICARUS or ChatGPT automation changes.
