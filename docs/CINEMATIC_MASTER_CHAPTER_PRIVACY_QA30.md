# QA30 — private master MP4 chapter inheritance

**Ownership:** Additive, opt-in QA only, stacked on lead #40 at `05c59556d64a808dcc3a8ca96fae5e572c9e446d`. No edits to `app/video/cinematic_service.py`, async queue, cache, mobile client, or other helper-owned files. Draft/unmerged.

## Reproduced behavior and threat

FFmpeg can copy chapter records (including chapter title tags) from an input MP4 into an output MP4 **even when the video is re-encoded using `-filter_complex`, `-map [v]`, `-an`, and `-movflags +faststart`**. The lead master assembly currently does not specify `-map_chapters -1`. This is a distinct metadata channel from source format/stream tags tested by #73; a fix that only adds `-map_metadata -1` is not a complete chapter-stripping policy.

Local controlled Linux FFmpeg reproduction before PR creation: a synthetic red H.264 clip with a single ffmetadata chapter produced a master with that chapter still present. This uses an invented sentinel, **not owner media**.

## Strict test contract

- Generate synthetic 10-second 160x90 H.264 footage, remux a one-second chapter into it, and confirm FFprobe reports exactly one source chapter.
- **GREEN control:** Re-encode with `-map_chapters -1`; FFprobe must report zero chapters, and FFmpeg must fully decode the resulting video.
- **Expected RED application integration:** Persist a synthetic project and succeeded shot job, call the real `assemble_project_master` implementation, and require the finished master to have zero chapters. Existing master metadata/codec checks do not inspect chapters.
- The assertion exposes only chapter count and a fixed error string, never tag values or paths. All fixtures live in a temporary workspace. General CI skips this opt-in expected-RED regression; the dedicated Python 3.11/3.12 workflow enables it.

## Lead review / integration

Review an explicit `-map_chapters -1` in master assembly **alongside** #73's `-map_metadata -1`, and consider stream tags, MP4 user data, chapter handling and the cache identity of previously assembled masters. Preserve private media paths, cancellation, frame accuracy, and durable queue provenance. Previously cached SHA-valid masters may retain source chapter metadata and require privacy revalidation or regeneration; do not silently mark them clean.

**Limits:** Genuine synthetic FFmpeg media is tested, but no owner media, real AI inference, owner-PC 600-second rendering, or physical iPhone playback. Dedicated RED is a production acceptance failure, not a broken test harness, if the control passes and the application assertion fails. Verify exact-commit CI before merging.
