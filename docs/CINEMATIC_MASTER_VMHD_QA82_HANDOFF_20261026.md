# QA82 — MP4 video media-header strict privacy acceptance (2026-10-26)

**Owner:** isolated QA82 offline-audit branch; draft PR #173; frozen parent QA81 PR #172 at `065ff9f12edc6e69407ea3b1f0f9e3865a227142`. **Do not merge automatically.**

## Reproduced defect and evidence

The narrow strict offline completed-master inspector accepts a valid ISO-BMFF `moov/trak/mdia/minf/vmhd` box without attesting its fixed FullBox length. An opaque synthetic suffix inserted inside this *allowed* video media header can be ignored by FFprobe and full H.264 decode, and a recomputed matching persisted SQLite SHA-256 is not proof of metadata privacy.

Test-only branch HEAD `caf73378efd934d4ce3793e676a80de6c3b08267`, dedicated genuine-FFmpeg Python 3.11/3.12 [workflow 40308671838](https://github.com/reppiks490/new/actions/runs/40308671838): Python 3.12 job `121524048084` completed expected **RED: 1 failed (strict falsely exited 0), 1 clean passed**. Python 3.11 status should be independently checked. The test remuxes to moov-at-end to avoid altering mdat offsets; verifies H.264, 48 frames at 24 FPS, 2-second duration, complete FFmpeg decode, and persisted SHA before asserting strict rejection. Only disposable synthetic media is used.

## Narrow proposed correction

Correction commit `d86da10e384797b1fc66a91e51f387620be14c2e` validates `vmhd` total box length against the 12-byte ISO-BMFF video media-header payload and its four nonprivate FullBox version/flags bytes (version 0, flags 1). It does not read, log, upload or retain private payload content. The legacy decode-only mode is intentionally unchanged. The new regression test and dedicated CI workflow are disjoint from other agents.

## Integration and acceptance boundaries

Dependencies: #8 master assembly; #21 durable async queue; #23 cache/media; #40 lead integration; QA81 #172 parent. Helper 1 #171 owns private HTTP cache policy; QA82 does **not** modify server, queue, worker, storage, router, mobile client or Helper 1 paths. Lead must inspect final-head dedicated/general/inherited CI and compatibility before integration. The strict allowlist can reject unusual muxers, and this is **not** comprehensive MP4 sanitization.

This evidence is genuine **synthetic FFmpeg** encode/remux/probe/decode plus temporary SQLite, **not** model inference, owner footage, physical mobile playback, Windows/owner-PC verification, complete 600-second render, production queue recovery or multi-worker fencing. No merges, deployment, paid services, cloud generation, owner secrets/media, ICARUS or ChatGPT automations changes.
