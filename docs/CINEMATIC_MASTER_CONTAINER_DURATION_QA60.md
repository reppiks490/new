# QA60 — MP4 container playback duration versus attested video timeline

**Draft only.** Stacked on QA59 #128 at frozen commit `74168ab0e5ffe3e64dd57d1a91ed7544d194838c`. This change touches only the QA54–59 **offline read-only** inspector and QA60-specific test, workflow and documentation. It is not wired into the production assembler, mobile client or queue.

## Reproduced false attestation

An MP4 can decode correctly and contain exactly 48 H.264 video frames at 24 FPS with correct per-frame presentation timestamps and durations (2.000 seconds), yet have a 5-second **container** duration because a synthetic silent AAC track extends beyond the video. A valid stored SHA-256 of that entire file still matches. The existing `--require-integrity` gate checked `format.duration > 0`, but did not compare the duration with the persisted video timeline; it returned success.

**Test-first genuine-media CI:** [run 40193940074](https://github.com/reppiks490/new/actions/runs/40193940074), Python 3.11 and 3.12: **1 intended failure and 1 clean control pass per version**. The failed assertion was precisely `timing_anomaly_count == 1` (actual 0), after the FFmpeg encoding, remux, FFprobe duration proof, SQLite record, full video decode, frame count and stored SHA checks succeeded. This is synthetic media only, not an owner footage incident.

## Proposed correction

After video frame parity and presentation cadence pass, compare the FFprobe **whole-container** duration with `timeline_frames / delivery_fps`, allowing at most one frame of muxer rounding. A real mismatch counts as a timing anomaly and blocks strict integrity success; absent/nonfinite duration evidence is unattested, not automatically corrupt. The existing decode-only default exit policy remains unchanged. All reports remain aggregate-only, with no paths, prompts, asset IDs or hashes, and no repair/deletion behavior.

Run only on a **quiescent, owner-selected local workspace**:

```bash
python tools/cinematic_completed_master_decode_qa54.py --workspace /path/to/private/workspace --database /path/to/private/workspace/studio.sqlite --require-integrity
```

This is a container playback-length check, **not** proof of audio/video synchronization, audio quality, source provenance, actual model inference, 600-second owner-PC rendering or physical mobile playback. The tool is not an atomic snapshot or a concurrent-writer security boundary. No paid services, cloud generation, deployments or merges were invoked.

Dependencies: master #8, async #21, cache/media #23, lead #40, parent QA59 #128. Concurrent Helper 1 #129 source-snapshot/CI work is intentionally untouched.
