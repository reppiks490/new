# QA57 — final-frame duration integrity for cinematic masters

**Scope:** isolated draft PR #125, stacked on QA56 #123 at exact parent `00c3242dc6cd9ddd2a783a1b48ab3dbdb341b0fd`. Changes are restricted to our own opt-in QA54–QA56 offline inspector and new QA57-only test, CI, and handoff files. No production assembler, queue, lead, Helper 1, mobile UI, ICARUS or automation changes.

## Genuine-media reproduced defect

A 48-frame, 24 FPS synthetic H.264/MP4 is encoded with libx264 and then remuxed with FFmpeg's `setts` bitstream filter. Only packet #47's duration is changed from 1/24 second to two seconds; the 48 presentation timestamps, frame count and full decode remain valid. FFprobe reports approximately **3.958 seconds** rather than the persisted **2 seconds**. Prior QA56 checked only each PTS and frame count, so it incorrectly reported `timing_attested_masters=1`.

**Test-first RED:** on test-only SHA `6dd1b95c3866d2395f4ed94608e9b58abae34d18`, [QA57 workflow 40181584401](https://github.com/reppiks490/new/actions/runs/40181584401) failed on the intended assertion (`timing_attested_masters` was 1 rather than 0) on Python 3.11 and 3.12. The normal 2-second control passed in each job; FFmpeg/ffprobe provisioning passed. This is synthetic evidence of a verifier gap, **not** evidence that owner media is damaged.

## Minimal correction

The read-only `_pts_cadence` FFprobe request now includes `duration_time` and legacy `pkt_duration_time`. It compares **each** decoded video frame's duration to `1 / delivery_fps`, including the final frame, with the same bounded timestamp-rounding tolerance as PTS checks. Missing duration metadata is *unattested* (not declared corrupt). A real mismatched duration is a timing anomaly. Existing QA54 decodability, QA55 frame parity, and QA56 PTS semantics stay separate.

The report remains aggregate-only. No paths, prompts, identifiers, credentials, FFmpeg stderr, or owner media are printed or uploaded; no deletion, repair, paid generation or cloud access. Run only on a **quiescent** owner-selected workspace; FFmpeg is not sandboxed for arbitrary untrusted files.

## Gates and dependencies

Final exact-head acceptance requires the dedicated Python 3.11/3.12 FFmpeg workflow, inherited QA54/QA55/QA56 workflows and ordinary Python/Node/Docker CI. This does not prove source-byte provenance, audio sync, real 600-second rendering, model inference, native 4K/120 FPS or physical iPhone playback.

Coordination: master assembly #8, async #21, cache/media #23, lead integration #40, QA56 #123, concurrent Helper 1 #124 (private snapshot crash recovery, different ownership). Keep draft/unmerged pending lead integration review. No force push, deployment, new services, ICARUS changes or ChatGPT automation changes.
