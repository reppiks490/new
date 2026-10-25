# QA49 — offline candidate untracked cinematic MP4 inventory

**Ownership:** Disjoint additive QA49 files only, based on the exact frozen lead #40 commit `05c59556d64a808dcc3a8ca96fae5e572c9e446d`. No production worker/router/storage or other helpers' files changed. Draft; do not merge automatically.

## Why this is useful

The master assembler in `app/video/cinematic_service.py` chooses a new UUID asset path and writes FFmpeg output **before** it persists a `video_master` record. Its Python `except Exception` deletes output after ordinary exceptions. An abrupt process/container kill cannot execute that cleanup, so an untracked MP4 **may** remain and consume private workspace disk. The earlier Docker restart #106 seeds a `running` record but does **not** actually kill a running encoder. This is a source-backed failure mode, not evidence of any owner-PC incident.

## Scope and interpretation

`tools/cinematic_orphan_media_audit_qa49.py` is an **explicit, offline, read-only** SQLite + local `video-assets/*.mp4` inventory. It reads **all** `video_job` and `video_master` rows, not the 100-row application history view; ignores malformed JSON without crashing; skips symlink media entries; reports only aggregate counts/bytes, missing completed references, active jobs and anomalies. No names, asset IDs, media paths, prompts, SQL row contents, FFprobe metadata, credentials or error strings are emitted. It neither deletes nor modifies media/DB, and never initiates rendering.

The term **candidate untracked** is intentional: an active FFmpeg process may be writing a new MP4 before its record exists; older manually imported assets may also lack rows. The `candidate_small_files_under_128_bytes` count is **not** a decoder or corruption verdict. Never automate deletion from this report. Quiesce local workers and reconcile project/job provenance before any owner-approved cleanup.

## Verification

Eight tests cover >100 historical records, missing completed assets, malformed JSON and structurally invalid statuses, active jobs, invalid IDs, privacy/no mutation, symlink boundaries, live WAL reads, and a **genuine synthetic FFmpeg-encoded H.264** clip alongside a manually truncated 64-byte candidate. The truncation simulates a possible partial file; it is **not** an actual killed FFmpeg encoder. The dedicated strict 3.11/3.12 workflow requires FFmpeg. Ordinary CI may skip only the real-media test if FFmpeg is absent; skipped tests are not passes.

Run only on a deliberate, offline, quiescent workspace, e.g.:

`python tools/cinematic_orphan_media_audit_qa49.py --workspace /private/local/studio --database /private/local/studio/studio.sqlite`

No owner workspace was accessed during QA. The audit does not prove actual model inference, owner-PC 600-second performance, physical iPhone playback, multi-worker fencing or complete recovery from an interrupted FFmpeg encode. Coordinate with #8/#21/#23/#40/#63/#95/#97/#102/#103/#105/#106; do not overwrite their branches or infer production readiness from green synthetic CI.
