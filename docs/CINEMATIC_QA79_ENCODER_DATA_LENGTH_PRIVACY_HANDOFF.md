# QA79 — NUL-hidden MP4 encoder data privacy

**Status:** isolated draft, do not merge. Frozen parent: QA78 #166 at `79f3af115158b0b6c6b6f413fea9f9f2f4c84fb6`. Parent exact-head workflows: **24 successes, 2 cancellations** (QA60 and QA58), not all green.

## Confirmed test-first defect

At test-only head `1cd8ddfe02be960d458c74d029edbf8265c52261`, [dedicated run 40288075466](https://github.com/reppiks490/new/actions/runs/40288075466) completed **FAILURE on Python 3.11 and 3.12**. Each job showed exactly **1 failed / 1 passed**, and the failure was the intended strict-audit assertion: actual exit **0** instead of required **1**, not fixture/setup failure.

A disposable synthetic FFmpeg H.264 MP4 contains a NUL and private canary *inside* the allowed `moov/udta/meta/ilst/©too/data` box. FFprobe reports a clean `Lavf...` encoder tag, 48 frames at 24 FPS and two seconds. Full decode, legacy decode-only and persisted temporary SQLite SHA succeed. Strict offline attestation incorrectly succeeded. No owner footage or remote exploit is implied.

## Proposed correction and boundaries

Commit `f228926f16689cae5a3c20debabf8f603182924a` changes only the opt-in, read-only offline completed-master inspector: compare the declared `data` box size against the already-probed, regex-validated ASCII `Lavf...` format encoder value, allowing exactly the eight fixed ISO metadata type/locale bytes, and verify those fixed bytes. This detects an invisible suffix without reading or reporting encoder payload. The clean control should continue passing; legacy decode-only remains unchanged. It is **not** a general metadata sanitizer, and unusual muxers can be rejected.

The new test and workflow use genuine synthetic FFmpeg/FFprobe H.264 and temporary SQLite, not mocks alone. Require dedicated Python 3.11/3.12 **final-head** success, general CI and inherited compatibility checks before marking ready. A cancelled check is not a success.

## Concurrent ownership and remaining gates

- Dependencies: #8 master assembly, #21 async queue, #23 cache/media, #40 integration, #166 QA78.
- Helper 1 #167/#168 owns cinematic Docker and private streaming/snapshot error handling. No production worker, queue, router, cache, mobile or Helper-1 file is modified.
- Actual model inference, private owner footage, full 600-second owner-PC render, physical mobile playback, comprehensive privacy sanitization and multi-process fencing remain unverified.
- No merge, deployment, paid/cloud generation, owner-media upload, force push, ICARUS or ChatGPT automation changes.
