# QA61 — Strict master single-video-track integrity (draft handoff)

## Scope and ownership
Stacked on QA60 draft PR #130 at `775ff0758163548c42b281830ca65328f572e367`.
Changes are restricted to this QA61 test, its dedicated workflow, this handoff,
and a narrow adjustment to the QA54–60 **offline read-only inspector**. No
production master assembler, durable queue, Helper 1 source-snapshot files,
mobile UI, owner footage, cloud generation, ICARUS or ChatGPT scheduler changes.

## Reproduced risk
An MP4 can contain two valid 48-frame 24-fps H.264 video streams and have
a two-second container duration, fully decodable first video stream, matching
persisted timeline/PTS/frame durations and matching persisted SHA-256.
The previous strict audit accepted any video stream in the FFprobe summary,
then inspected only `v:0`. A mobile player may select a different track,
so the audit must not certify an ambiguous multi-video-track master.

## Correction
The opt-in `--require-integrity` gate now rejects any otherwise-valid
completed master whose probed MP4 has anything other than exactly one video
stream. The report exposes only `video_stream_anomaly_count`, never media
identifiers, paths, prompts or hashes. The historical decode-only exit policy
is unchanged. No media is repaired, opened for modification or deleted.

## Verification boundaries
The new tests create **real synthetic FFmpeg H.264** MP4s and temporary SQLite
records. They do not use mock-only FFmpeg success, owner footage, AI inference,
600-second local renders or a physical iPhone. Passing strict integrity still
does **not** prove audio correctness, source lineage, codec support on every
device or actual mobile playback. This check enforces a narrow single-video
delivery invariant only.

## Merge/dependency policy
Keep draft and unmerged pending integration-owner review. Parent chain:
#130 → #128 → #127 → #125 → #123 → #121 → #119 → #116 → #114 → #112 →
#110 → #109 → lead #40. Async #21 and cache acceptance #23 remain separately
owned. Helper 1 source-snapshot work is separate. No force pushes or automatic
merges. Review final exact-commit GitHub Actions evidence before acceptance.
