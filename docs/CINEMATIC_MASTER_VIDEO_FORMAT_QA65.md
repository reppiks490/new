# QA65 — Strict mobile video-format attestation (draft / do not merge)

## Frozen ownership and integration
Parent: QA64 PR #137 exact `0b34816865f465502fac727498a9b7810ccd78c2`.
Dedicated branch: `chatgpt/cinematic-master-video-format-qa65-20261025`.
QA65 owns only a new test, workflow, this note and (only if test-first RED proves a defect) a narrow addition to our existing read-only offline inspector `tools/cinematic_completed_master_decode_qa54.py`. It does **not** change production assembly, master queue, cache, source-snapshot fencing, mobile UI, owner footage, credentials, inference, cloud services or ICARUS.

## Hypothesis / test-first evidence boundary
The existing strict gate checks decoding, frame count, PTS/duration, container duration, SHA-256, single video track and AAC audio, but its video-stream metadata probe does not inspect codec or pixel format. A valid two-second 48-frame/24-fps MP4 encoded with MPEG-4 Part 2, or with H.264 4:4:4 pixel format, may be accepted despite the intended H.264 8-bit 4:2:0 mobile delivery contract.

A deterministic disposable-media regression uses real FFmpeg/FFprobe to construct H.264/yuv420p (positive control), MPEG-4/yuv420p (codec mismatch), and H.264/yuv444p (pixel-format mismatch), with SQLite hash claims updated to match the exact files. Both legacy decode-only mode and opt-in strict mode are checked. Strict must reject the latter two even if video fully decodes and existing timeline/hash checks succeed.

**Test-first RED evidence:** [GitHub Actions run 40217212559](https://github.com/reppiks490/new/actions/runs/40217212559), original test-only HEAD `e6e713f31386ec95497ed9c5eac6489afe1556fa`. Python 3.11 job `121240843279` reproduced three expected failures using genuine synthetic FFmpeg: H.264/yuv420p positive control passed the legacy and strict exit checks but exposed missing diagnostic counters; MPEG-4/yuv420p and H.264/yuv444p both incorrectly returned strict exit 0 while their independent FFprobe/decoded frame, timing and SHA preconditions passed. Python 3.12 was still provisioning FFmpeg at the RED checkpoint and is **not** counted as completed. This is codec/container acceptance, not physical phone playback.

## Narrow correction after reproduced RED
The proposed offline inspector now probes `codec_name` and `pix_fmt` on the unique video stream, classifies known mismatches separately from missing evidence, reports aggregate-only counters and fails only the opt-in strict integrity gate. Preserve legacy decode-only CLI compatibility, video-only masters and privacy of paths, prompts and bytes. No automatic deletion.

## Dependencies / remaining acceptance
Lead integration PR #40, master #8, async queue #21, cache/media #23 and Helper 1 source-provenance PR #138 are separate draft work. Any combined integration requires lead approval and new final-SHA CI. No model inference, 600-second owner-PC render, owner footage, lip-sync or physical mobile playback is established by this offline QA.

## Verification status

Final correction commit `41a6bed19987a8982160a1fa89098ee5f4baee72` is **not** the final docs HEAD; recheck exact final HEAD and all workflow conclusions before claiming green. The initial RED is not proof of a passing fix. If CI provisioning or inherited workflow cancellation occurs, report those checks as incomplete rather than green.
