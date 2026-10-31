# QA56 — decoded master presentation-timestamp cadence audit

**Draft PR #123**, stacked on QA55 #121 at exact commit `4bcd77f3b91f461d0799f8d3cbcf6095629f777b`. Scope: our own optional QA54/QA55 offline inspector, QA56-only tests/CI/handoff. No production master assembler, async queue, owner media, mobile UI, lead-owned files or Helper 1 source-provenance proposal changes.

## Reproduced limitation

QA54 full decode and QA55 decoded-frame parity are **not** proof of presentation-timestamp cadence. A genuinely encoded synthetic 48-frame H.264 file at 24 input frames/second, re-timestamped with `setpts=2*PTS` and muxed with passthrough frame synchronization, still fully decodes to 48 frames. Its frame count matches a synthetic 48-frame SQLite claim, but the presentation timeline is stretched to nearly four seconds rather than two. This is a synthetic reproduction of a possible integrity gap, **not** evidence that owner media is affected.

The test-only commit `fd96a94d0ad581f805f81fa2ed3d65043126a298` produced genuine assertion-level RED in [QA56 CI run 40177539008](https://github.com/reppiks490/new/actions/runs/40177539008): 5 intended missing-attestation failures and 10 inherited QA54/QA55 passes on Python 3.11 and 3.12; FFmpeg provisioning succeeded. A subsequent separate commit implements the timing inspection.

## New read-only attestation

Run only against a selected **quiescent** local workspace:

```sh
python tools/cinematic_completed_master_decode_qa54.py --workspace /local/studio --database /local/studio/studio.sqlite --timeout 120
```

For each successfully decoded master with matching `timeline_frames` and `probe.frame_count`, QA56 requires one consistent positive `delivery_fps` claim. It uses real FFprobe per-frame `best_effort_timestamp_time` values to check frame count, zero-based start and each timestamp/cadence against the expected constant-frame-rate grid within a small timebase rounding tolerance. It reports only aggregate `timing_attested_masters`, `timing_unattested_masters`, `timing_anomaly_count`, and `timing_attestation_complete`.

Missing/ambiguous legacy FPS claims or failed timing probes remain **unattested**, not declared corrupt. Genuine timestamp mismatches are anomalies. QA54 `verification_complete` still means decodability; QA55 `timeline_attestation_complete` still means decoded frame parity; neither is silently redefined. No filenames, project IDs, prompts, owner paths, FFmpeg stderr or asset hashes are printed. No repair, deletion, cloud generation or uploads.

## Verification boundaries and dependencies

The dedicated workflow requires real FFmpeg and FFprobe on Python 3.11 and 3.12 and exercises genuine synthetic MP4s plus temporary SQLite. The regular CI matrix remains independent. A per-process timeout bounds each probe, and unexpectedly large JSON timing output is rejected, but FFmpeg/FFprobe are **not** sandboxed for untrusted media; run only offline on a quiescent workspace. The timing audit is an opt-in read-only diagnostic, not a production guarantee or a substitute for audio sync, source-byte provenance, edit continuity, complete 600-second owner-PC rendering, actual AI model inference, native 4K/120 FPS or physical iPhone playback.

Coordinate master #8, async #21, cache/media #23, lead #40, parent #121, and concurrent Helper 1 #122 (source snapshots). No automatic merge/deployment, purchases, credentials, owner-media transfers, ICARUS changes or ChatGPT automation changes.
