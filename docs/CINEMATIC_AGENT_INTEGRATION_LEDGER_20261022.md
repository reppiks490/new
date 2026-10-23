# Cinematic Orchestrator — review-safe multi-agent integration ledger

**Snapshot:** 2026-10-22 (America/Chicago). **Repository:** `reppiks490/new`. **Integration target:** `feat/cinematic-orchestrator-v1`.
**Nature:** coordination and dependency ledger, **not** authority to merge, deploy, pay providers, or alter another agent's work. Re-read the live GitHub PR heads and checks before any actual action.

## Source-of-truth merge sequence — proposed, not executed

1. **Foundation — PR #8** (`chatgpt/cinematic-master-assembly-20261022`). Batch renders, project status, FFmpeg concat, SHA-256 lineage, ffprobe final verification, private routes. Verified baseline head `9e8e7ea`. Remains draft and unmerged.
2. **Master cache fix and mandatory real-media gate — PR #23**. It corrects the verified-probe cache lookup and adds genuine FFmpeg acceptance tests/CI. Prefer this coherent combined candidate to merging the narrower duplicate proposals **#22, #20 and #15** independently. Verify their differences before marking superseded. PR #23 has successful reported checks at head `c015ad1`.
3. **Async master worker — PR #21** (`chatgpt/cinematic-async-master-jobs-20261022`). SQLite queue, single CPU lane, atomic claim/cancel, revision validation, neutral status, startup recovery, authenticated polling. Baseline `fd4e62e` had two green workflow runs. Must reconcile with the preceding cache fix without destructive rebase/force-push.
4. **Mobile privacy/queue client — PR #28** (`chatgpt/cinematic-mobile-assembly-client-20261022`). Sanitized job status, exact verified asset URI, bounded reconnect retries, abortable scanning and polling, queued cancellation. New independent bounded private-MP4 preview gate and byte-stream/HTTP cancellation. Latest implementation head may change; final-head CI remains required. **Current preview is intentionally not yet wired into the owner UI and refuses oversized films**.
5. **Reconnect pagination correctness — PR #33**. Mutating offset-paginated history can skip the active job. This independent fix is based on an earlier PR #28 commit: review its tests and reconcile all subsequent PR #28 additions in the same client module before adopting.
6. **Other additive experts:** Helper 2's capability/timeline/reference preflight **#16**, later invalid-metadata child **#35**; Helper 3's frame-exact editorial preflight **#18** (and older **#9**); Helper 4's timeline, restart and long-film QA **#24** (and older **#12**); Helper 1's async bearer isolation **#25**, cancellation QA **#31**, result binding QA **#34**, authenticated real-media gate **#32**. Merge by real content and verified revision, never solely by PR number or green badge.
7. **Creative-edit freshness — PR #29** proposes clearing outdated source render links after effective shot changes. Keep distinct until the preservation/invalidation semantics and matching regression tests are reviewed.
8. **Broad composite validation PRs #26, #27, #30**: treat as integration/acceptance evidence, not replacements for each owner's reviewable source PR. Such branches may contain overlapping files and stale upstream versions. Avoid blindly merging a composite and all its source changes twice.

## Strict evidence and ownership gates

- Each reviewer must inspect **exact HEAD**, not a previous successful workflow commit. Require Linux Python 3.11 and 3.12, browser Node tests, Docker, plus the dedicated real-FFmpeg decode/cache integration where applicable.
- Python 3.11 intermittently reported a separate Blender adaptive-subdivision native crash (`malloc(): invalid size`) in `tests/test_blender_live.py::test_render_applies_displacement_with_adaptive_subdivision`. Preserve its failure evidence; don't ignore, remove, or conditionally skip the test to make a cinematic PR green. Distinguish a Blender crash from a cinematic client regression.
- Mock MP4 headers do not prove playable video. Real synthetic FFmpeg validation does not prove GPU model inference, creative continuity or authentic iPhone playback.
- Source and output hashes, codec, FPS, frame count, exact authored duration, private bearer headers, range/memory behavior, restart recovery and stale-project rejection each need separate evidence.
- Keep owner tokens, prompts, images, model weights, and private video bytes out of public Git history, issues and status artifacts.
- No new paid APIs, unrestricted GPU launches, external publishing, live production deployment, branch renames, resets or forced pushes.
- Browser preview cannot simply load a multi-gigabyte 4K master into a Blob. PR #28's bounded helper refuses media above its configured threshold; genuine long-film authenticated streaming/proxy delivery and owner-hardware/iPhone acceptance remain unsolved.
- The next UI task should wire the reviewed client to the cinematic editor without colliding with the UI agent; Quick Hide/mode-exit must cancel polling and network preview, revoke object URLs and leave prompts concealed.

## Handoff protocol

Every agent should post on its **own PR**: exact changed file list, pinned base/head SHAs, test methods and real results, missing providers/hardware, overlap with other PRs, and one non-destructive integration path. Use narrow cross-PR comments to claim or yield specific file ownership. Do not assume another chat can receive direct messages or execute a background tool: repository documents and PR comments are the shared coordination bus.

The already-enabled **Cinematic Build Continuation** hourly ChatGPT task may perform additional bounded evidence-backed cycles; it is not a substitute for a real PC worker/service, CI, deployment or acceptance testing.
