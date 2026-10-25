# QA69 — strict offline cinematic master nested MP4 payload acceptance

**Scope:** Draft proposal stacked on QA68 #146 (`c540312ccbdd01d64deacea3563d6f1bc0924236`), not production master assembly, cloud generation, local model inference or mobile playback. No owner media/credentials, deletion, deployment, merge, or ICARUS/automation edits.

## Verified RED evidence

[Test-first workflow 40236609393](https://github.com/reppiks490/new/actions/runs/40236609393) completed **FAILURE on Python 3.11 and 3.12** at test-only commit `662f5b08ab0c4d3b383a14ed82479f8411209f1b`. Both versions reproduced two incorrect strict successes for opaque immediate `moov/free` and `moov/uuid` children, plus the deliberately missing diagnostic counter on the clean control. The fixture is genuine synthetic FFmpeg/libx264 H.264, 48 frames at 24 FPS, with temporary SQLite storing the actual media SHA-256. Remuxing to end-of-file `moov` before inserting a child avoids invalidating chunk offsets; FFprobe reports clean stream/tag/chapter data and full FFmpeg decode succeeds. No mock-only proof is substituted for actual synthetic media.

## Narrow proposed correction

The offline inspector `tools/cinematic_completed_master_decode_qa54.py` now scans only **immediate children of the `moov` atom** in bounded memory. Nonempty `free` children and any `uuid` child are strict privacy anomalies. Malformed child headers/lengths fail closed; uncertain filesystem evidence is reported separately as unattested. Clean `moov` and empty `free` padding remain allowed. Counters `nested_mp4_payload_anomaly_count` and `nested_mp4_payload_unattested_count` are aggregate only and contribute to the opt-in `integrity_attestation_complete` gate. Existing decode-only CLI remains backward compatible; no bytes, metadata values, filenames, hashes, prompts or decoder stderr are printed or transferred.

## Integration, CI and limitations

Dedicated QA69 real-media CI must pass on both Python 3.11/3.12 **at the exact final commit**, along with inherited QA54–QA68 and general Python/Node/Docker CI. The QA68 parent #146 had 14 successful and **two cancelled** final-head workflows (QA59 and QA63); it must not be called fully green without rerun. This proposal does **not** inspect deeper `trak`, `udta` or `meta` descendants, embedded pixels, codec steganography, Windows ACLs, or every valid ISO-BMFF variant; it is not comprehensive sanitization or a substitute for authenticated media serving and source provenance.

Owners of lead #40, master #8, async #21 and cache acceptance #23 must decide whether to integrate this optional offline gate. Concurrent Helper 1 #148 owns the separate cached-master symlink race and remains untouched. Actual model inference, owner-PC 600-second rendering, multi-worker recovery and physical iPhone/mobile playback are unverified.
