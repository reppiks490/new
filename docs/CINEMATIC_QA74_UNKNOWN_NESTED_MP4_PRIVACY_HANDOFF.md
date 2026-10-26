# Cinematic QA74 — unknown nested MP4 box privacy acceptance

## Ownership and integration

Draft-only, isolated continuation of QA73 #156 (frozen base `f5e6b5ca1f2157777b957b944dde347d7fe80e29`). Only the offline, opt-in, read-only completed-master inspector is modified; the new QA74 regression and CI workflow are isolated files. No production FFmpeg worker, durable queue, cache, authenticated media route, mobile UI, owner media or cloud generation is changed.

## Failure mode and evidence contract

QA68–QA73 inspect top-level and selected nested MP4 `free` and `uuid` payloads. Before QA74, a different, unrecognized nested four-character box (synthetic `priv`) was not rejected at the five inspected levels. FFprobe's public stream and tag inventory may ignore such a box while H.264 frames decode and the persisted SQLite SHA-256 matches the entire MP4. The SHA verifies bytes, **not absence of private auxiliary bytes**.

QA74's genuine synthetic FFmpeg regression inserts a canary into an unknown child of `moov`, `trak`, `mdia`, `minf` or `stbl`, and includes a clean control. Each case must retain H.264 decode, 48 frames at 24 FPS, two-second timing, a matching stored hash and a successful legacy decode-only check. Strict mode must reject the five unknown-child cases, report only aggregate counters and never disclose the canary.

## Proposed mitigation and limitations

The strict offline scanner now uses explicit conservative allowlists of known FFmpeg/ISO-BMFF structural children at those five levels, retaining only zero-payload `free` padding. Unknown children fail strict attestation; legacy decode-only behavior remains unchanged. The scanner reads bounded headers and checks file stability rather than loading owner footage into memory.

This is **not** comprehensive MP4 sanitization. Nested metadata within permitted `udta`/`meta`, sample descriptions, video/audio pixels and other deeper boxes are outside the new contract. An allowed box can still carry problematic contents. The strict allowlist may conservatively reject an otherwise valid MP4 produced by a different encoder or muxer. Such compatibility should be evaluated with authorized synthetic variants before broadening the contract.

## Acceptance and next steps

Check the **test-only commit** workflow for actual RED failures, then the **final commit** for green QA74 on Python 3.11 and 3.12, inherited QA54–QA73, general Python/Node/Docker CI, and exact-head branch compare. Do not count queued jobs as passed. Keep draft/unmerged pending lead review and combined-branch verification with #8, #21, #23 and #40.

Separate unverified goals: actual model inference, production crash fencing, owner-PC 600-second local render, physical mobile playback and owner footage. No owner files, credentials, paid services, deployments or live media generation were used in this QA cycle.
