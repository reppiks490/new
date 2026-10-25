# QA70 — strict offline cinematic master trak-child MP4 privacy handoff

**Scope:** Isolated draft #150 stacked on QA69 #149 exact `cfcd8f6a958f508385c58acbfaa9f9977de2ced2`. The parent has 17/17 successful exact-head workflows (including Python 3.11/3.12 dedicated real-media and general CI). No production assembly/async queue/cache, mobile UI, Helper 1 #148, owner media, credentials, cloud generation, merges, deployment or automation changes.

## Confirmed test-first defect

[Test-only QA70 CI 40240965164](https://github.com/reppiks490/new/actions/runs/40240965164) **failed on both Python 3.11 and Python 3.12 as intended**: each version passed two controls and failed the two strict false-success regressions for nonempty `moov/trak/free` and `moov/trak/uuid` payloads. Both cases used disposable **genuine FFmpeg H.264**, 48 frames at 24 FPS, clean FFprobe stream/timing metadata, successful full video decoding and matching persisted temporary SQLite SHA-256. Private canaries were synthetic and not exposed in audit JSON. This is real synthetic media testing, **not** model inference or owner footage.

## Narrow correction proposal

The existing read-only `tools/cinematic_completed_master_decode_qa54.py` now inspects immediate children of `trak` while already scanning `moov` children. Reject any `uuid` and nonempty `free` boxes or malformed bounds; allow clean tracks and empty padding. Bounded header-only scanning; no media bytes, metadata values, file paths, prompts or hashes emitted. Reuse the existing aggregate `nested_mp4_payload_anomaly_count` strict gate; legacy decode-only behavior remains backward compatible. The correction is proposed for review, not automatically integrated into production.

## Verification and limitations

Check **exact final branch HEAD** for the QA70 Python 3.11/3.12 genuine FFmpeg workflow, inherited QA54–QA69 and general Python/Node/Docker checks. A test-first RED run is not a final GREEN claim. Other MP4 descendants (`mdia`, `meta`, `udta`), encoded-pixel steganography, race-free source provenance, 600-second owner-PC rendering, actual inference, audio perception and physical mobile/iPhone playback remain outside this proof. Multi-worker queue recovery and final lead integration remain separate. Owner/lead approval is required; do not auto-merge, deploy or buy services.
