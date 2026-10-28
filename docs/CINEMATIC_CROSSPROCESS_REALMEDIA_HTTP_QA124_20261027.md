# Character3D QA124 — independent-process genuine synthetic media / private HTTP

**Frozen parent:** QA123 draft PR #224 at `7b283018b6cb5c4ae84c34f62ce0ebf08861076f`.
**Ownership:** only three new QA124-specific paths: test, opt-in dedicated CI, and this handoff.
**Policy:** draft / DO NOT MERGE without lead integration review; no owner footage, credentials, paid services, inference, deployment, or automation changes.

## Why this acceptance is valuable

QA123 #224 proved real cross-process SQLite transitions with **synthetic master metadata**, not an MP4. Existing `test_cinematic_async_real_media_integration.py` proved real local FFmpeg and authenticated HTTP with an **in-process queue drain**. QA124 bridges the two without modifying shared production or helper files:

1. Create a genuine disposable Character3D project with two real FFmpeg color MP4s (red 24 fps, blue 30 fps), 5 seconds each.
2. Submit an authenticated async master request via real FastAPI; hold only executor submission to prevent in-process drain.
3. In a **different Python interpreter**, atomically claim the real SQLite WAL job and wait on a filesystem gate. Parent observes the running status through private HTTP.
4. Release the child, invoke the **actual** `_execute_one` and `assemble_project_master` with FFmpeg/FFprobe, and persist real master metadata.
5. Reconnect with a fresh FastAPI TestClient and verify terminal status, owner-only media GET, 206 Range, no-store on authorized media, byte-for-byte SHA-256, ffprobe codec/geometry/fps/240 frames, full FFmpeg decode, and red-then-blue visual order.

No fake `video_master` is inserted and the actual assembly function is **not mocked**. The test is opt-in in the general matrix; a dedicated Ubuntu Python 3.11/3.12 job installs FFmpeg/FFprobe and enables it. An ordinary skipped test must not be represented as real-media evidence.

## Boundaries and dependencies

This is **synthetic CPU-generated 854x480, 10-second** video, not 600-second 4K, not actual model inference, not artistic identity/continuity, not owner Windows/WSL2 performance and not physical iPhone/mobile playback. The HTTP client is in-process TestClient; the FFmpeg worker is a separate operating-system process. It does **not** exercise two simultaneously running API servers or resolve #200's startup recovery hazard; **one API server process per shared SQLite workspace remains required**.

Existing unresolved issues: #200 live-worker recovery, #215 duplicate executor submissions, #201 source AAC audio policy, #204 missing no-store on private denial responses, #213/#214 Bearer scheme integration, #171 Helper 1 middleware, and final combined-SHA integration #40. QA124 does not touch #8 master, #21 queue, #23 media cache, #40 integration, or Helper 1 #223 HTTP cancellation files. Check final PR merge-candidate CI before any acceptance claim; test success alone is not release readiness.

## Verification ledger

At creation, test and workflow are **unverified**. Update with exact commit SHA, dedicated run IDs, general CI results and any failures. No automated merge.
