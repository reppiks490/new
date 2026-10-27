# QA111 — Genuine synthetic 4K private HTTP Range acceptance (2026-10-27)

**Scope/owner:** Independent QA-only continuation on frozen QA110 #211 commit `62fe2c53eb552b637f15155bc8692e27f80fcef1`. Dedicated branch `chatgpt/cinematic-4k-private-range-qa111-20261027`; draft/unmerged; no shared production or other-agent files touched. Three new QA111-owned paths: this document, `tests/test_cinematic_4k_private_http_range_qa111.py`, and `.github/workflows/cinematic-4k-private-http-range-qa111.yml`.

## Why this acceptance matters

QA110 #211 established actual Character3D **10-second 4K master assembly**, and QA102 #203 established **600-second 480p** authenticated byte ranges. Neither independently verifies the combination of 3840×2160 application-generated media and its actual private HTTP Range delivery. QA111 assembles a disposable two-shot red/blue 4K H.264 master with real FFmpeg, then exercises the FastAPI middleware and FileResponse using TestClient. It checks the exact private MP4 bytes at beginning, middle, and end, including 206, Content-Range, Content-Length, video/mp4, and no-store for successful responses. It also checks missing/wrong/query-only bearer denial and out-of-bounds Range 416.

This is **genuine synthetic local FFmpeg media and in-process HTTP acceptance**. It is not actual model inference, a real 600-second 4K encode, remote transport, owner Windows/WSL2 verification, browser media element, phone hardware decode, or physical playback. The test deliberately does not claim the existing unauthorized-401 cache-control defect is fixed: QA103 #204 and Helper 1 #171 already own that finding/correction.

The dedicated opt-in workflow runs in offline nonroot read-only-root Docker with disposable tmpfs and no external service credentials. General CI skips the test unless `CINEMATIC_4K_PRIVATE_RANGE_QA111=1`. A green general CI without a successful dedicated workflow is **not** proof of this acceptance.

## Dependencies and known blockers

- Master assembly #8, durable async queue #21, cache/media #23 and lead integration #40 require a single reviewed combined SHA and combined-commit CI. This QA branch does not integrate or modify their work.
- Helper 1 privacy #171 and strict-media integration gate #194 are divergent draft dependencies, not combined proof.
- QA99 #200: multi-process startup recovery may invalidate a live worker; inherited strict xfail remains unresolved.
- QA100 #201: source AAC is stripped from masters; audio-preservation policy is unresolved.
- QA103 #204: unauthorized private-media denial lacks explicit no-store; this QA111 test checks 401 without masking or claiming correction.
- No merge, deploy, paid generation, owner media/credentials, ICARUS, or automation changes are authorized.

## Evidence contract

Verify the **exact final commit** with both general CI and the dedicated `Cinematic genuine 4K private HTTP Range QA111` workflow. A queued/failed/skipped dedicated test cannot be reported as passing. Record any failure as test, application, or environment evidence before changing production. Post coordination on lead #40 and the dependent PRs. Preserve the branch as draft.
