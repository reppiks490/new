# QA55 — completed cinematic master decoded-frame attestation

**Draft PR #121**, stacked on QA54 #119 at `a5cfdd432007d325514ae4c1c601d6b19d92e914`. Changes only our QA54 opt-in inspector and three QA55-owned paths (test, workflow, handoff). No production assembler, async queue, lead or Helper 1 files, mobile UI, default Dockerfile, private media, credentials, deployment or scheduler changes.

## Evidence-backed gap

QA54 deliberately established that completed MP4s can be **fully decoded**, not that their actual decoded frame count agrees with the authored timeline. Production `assemble_project_master` persists `timeline_frames` and `probe.frame_count` on a `ready` `video_master` record. A 24-frame genuine H.264 MP4 can fully decode even when a record claims 48 frames. FFmpeg/FFprobe synthetic reproduction is local only; there is no evidence of an affected owner asset.

QA55 adds five strict real synthetic FFmpeg/SQLite regression tests: matching 48-frame attestation, 24-frame short media claiming 48, legacy row lacking timeline evidence, inconsistent stored probe count, and conflicting duplicate ready rows. Tests were committed before the fix; do not confuse runner provisioning errors with assertion-level RED evidence.

## Opt-in operation and interpretation

Use the **same offline, owner-selected quiescent-workspace** command as QA54:

```sh
python tools/cinematic_completed_master_decode_qa54.py --workspace /local/studio --database /local/studio/studio.sqlite --timeout 120
```

QA54's `verification_complete` retains its original **decodability-only** meaning for compatibility. QA55 adds independent `timeline_attested_masters`, `timeline_unattested_masters`, `timeline_frame_mismatch_count`, and `timeline_attestation_complete` counters. Only an actual successful FFmpeg full decode with final `progress=end` and a frame count equal to a unique consistent positive `timeline_frames` and `probe.frame_count` claim earns timeline attestation. Missing/ambiguous legacy claims remain **unattested, not declared corrupt**. A mismatch does not authorize deletion or repair.

FFmpeg uses `-fps_mode passthrough` so the null output does not duplicate/drop decoded frames for timestamp synchronization. Progress output is parsed in-process; no media paths, prompts, IDs, FFmpeg stderr or owner metadata are printed. The inspector remains read-only; no external network or shell execution, no automatic deletion. Each file's subprocess has its own timeout. It is not a sandbox for untrusted media, and filesystem mutation races remain possible.

## What is **not** proven

Frame-count agreement is not frame-by-frame visual continuity, exact presentation timestamps, audio sync, correct FPS/duration/colorimetry, SHA-256 source provenance, full 600-second owner-PC render, model inference, native 4K/120 FPS or physical iPhone playback. A maliciously false database claim matching the wrong media cannot be distinguished without independent project/source attestation. The existing QA54 full-decode verdict remains separate.

Coordinate with master #8, async queue #21, cache/media #23, lead #40, QA54 #119 and concurrent Helper 1 #120. Keep draft, never auto-merge. No cloud generation, purchases, deployment, owner media or ICARUS/ChatGPT automation changes.
