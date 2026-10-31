# QA62 — optional master audio stream coverage (2026-10-25)

## Frozen scope and ownership

Draft PR #133, based on QA61 #132 commit `7146a9a419f25432692d8d58f31e0a64e385fd43`.
Only the existing QA54–61 **offline, read-only** completed-master inspector plus new QA62 tests, CI, and this handoff are touched. No production assembler, queue, mobile UI, Helper 1 source-snapshot code, owner footage, cloud service or model inference is involved.

## Test-first reproduced defect

A valid 48-frame/24-FPS 2-second H.264 video can have a 0.5-second AAC track or a 1-second-delayed AAC track, yet the MP4 container remains 2 seconds. The original strict inspector verified video decode, frame count, frame timestamps, overall MP4 duration and persisted SHA-256, but not the audio stream's start and end. It returned successful strict exit for these incomplete audio examples. A dual-audio-track MP4 likewise passed.

**RED**: dedicated genuine synthetic FFmpeg/SQLite workflow run [40203270622](https://github.com/reppiks490/new/actions/runs/40203270622), Python 3.11 and 3.12. Each had three direct assertions `expected exit 1, got 0` for short, delayed and dual-audio media; two positive controls failed only because the new diagnostic counters were absent. FFmpeg/FFprobe provisioning and actual synthetic encoding succeeded.

## Narrow correction

The opt-in `--require-integrity` gate now rejects multiple audio tracks and a single audio track whose FFprobe start/end contradict persisted `timeline_frames/delivery_fps` by more than one frame. Missing/nonfinite audio timing evidence is **unattested**, not asserted corrupt. Video-only remains allowed, and normal aligned AAC passes. The legacy default CLI exit remains decode-only and backward compatible.

The report contains only aggregate anomaly/unattested counters. No paths, IDs, hashes, prompt content, media uploads, deletion or repairs are performed.

## Verification and limits

Tests create disposable synthetic H.264/AAC MP4 files and temporary SQLite records. This is stream-metadata coverage, **not** decoded audio quality, semantic synchronization, source-audio provenance, actual model inference, owner-PC 600-second rendering or physical mobile playback. Multi-language/multi-track audio delivery is intentionally not attested by this strict single-track policy and requires explicit owner/product review if desired.

Final exact-HEAD CI results must be recorded before considering this branch ready. Keep draft/unmerged pending lead review and stack integration.
