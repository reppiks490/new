# QA65 — Strict mobile video-format attestation (draft / do not merge)

## Frozen ownership and integration
Parent: QA64 PR #137 exact `0b34816865f465502fac727498a9b7810ccd78c2`.
Dedicated branch: `chatgpt/cinematic-master-video-format-qa65-20261025`.
QA65 owns only a new test, workflow, this note and (only if test-first RED proves a defect) a narrow addition to our existing read-only offline inspector `tools/cinematic_completed_master_decode_qa54.py`. It does **not** change production assembly, master queue, cache, source-snapshot fencing, mobile UI, owner footage, credentials, inference, cloud services or ICARUS.

## Hypothesis / test-first evidence boundary
The existing strict gate checks decoding, frame count, PTS/duration, container duration, SHA-256, single video track and AAC audio, but its video-stream metadata probe does not inspect codec or pixel format. A valid two-second 48-frame/24-fps MP4 encoded with MPEG-4 Part 2, or with H.264 4:4:4 pixel format, may be accepted despite the intended H.264 8-bit 4:2:0 mobile delivery contract.

A deterministic disposable-media regression uses real FFmpeg/FFprobe to construct H.264/yuv420p (positive control), MPEG-4/yuv420p (codec mismatch), and H.264/yuv444p (pixel-format mismatch), with SQLite hash claims updated to match the exact files. Both legacy decode-only mode and opt-in strict mode are checked. Strict must reject the latter two even if video fully decodes and existing timeline/hash checks succeed.

**At creation:** Test-first CI pending. No defect or fix is claimed until observed; do not count mock tests as real media or interpret codec/container checks as physical mobile playback.

## Desired narrow correction if reproduced
Probe `codec_name` and `pix_fmt` on the unique video stream, classify known mismatches separately from missing evidence, report aggregate-only counters and fail only the opt-in strict integrity gate. Preserve legacy decode-only CLI compatibility, video-only masters and privacy of paths, prompts and bytes. No automatic deletion.

## Dependencies / remaining acceptance
Lead integration PR #40, master #8, async queue #21, cache/media #23 and Helper 1 source-provenance PR #138 are separate draft work. Any combined integration requires lead approval and new final-SHA CI. No model inference, 600-second owner-PC render, owner footage, lip-sync or physical mobile playback is established by this offline QA.
