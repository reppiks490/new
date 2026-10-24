# QA31 — Closed MP4 stream inventory for private mobile masters

**Scope:** Optional, read-only offline acceptance; no production changes, owner media,
credentials, cloud generation, broker actions, deployments or automatic merges.

## Reproduced gap

The existing QA17 `verify_master()` checks the trusted SHA-256, metadata and
full FFmpeg decode of **video stream 0 only** (`-map 0:v:0`). It does not
inventory other MP4 tracks. A two-second synthetic MP4 with two independent
H.264 video tracks (48 frames each at 24 FPS) passes that first-video gate
even though it carries an additional video track. A synthetic MP4 with an
embedded `mov_text` subtitle track likewise passes the first-video gate.

This is a **verification blind spot**, not proof that the current production
master assembler leaks extra tracks: the lead assembler in PR #40 explicitly
maps its one generated video output and uses `-an`. The risk concerns
future encoders, imported/cached masters and broad claims of mobile/privacy
acceptance when only the first stream was inspected.

## Added acceptance gate

`scripts/cinematic_mobile_stream_inventory_preflight_qa31.py` first calls
QA17's trusted SHA and full first-video decode. It then asks FFprobe for a
minimal stream inventory, rejects a second video track and rejects subtitle,
timed-data, attachment or unknown streams. Silent masters are the default.
A caller may explicitly allow **one AAC audio track**, but this check verifies
only its codec identity, **not audio decode or A/V synchronization**; QA21/QA22
remain separate. The tool never reports paths, source metadata, prompts or
credentials, and it does not mutate the MP4.

Example for a **trusted, locally persisted** master:

```bash
python -m scripts.cinematic_mobile_stream_inventory_preflight_qa31 \
  --mp4 /private/local/master.mp4 --expected-sha256 <trusted-64-hex> \
  --fps 24 --frames 240 --width 854 --height 480
```

The output contains only neutral verification booleans and stream counts.
The optional `--allow-aac-audio` switch does not imply audio decode.

## Strict synthetic evidence

`CINEMATIC_REQUIRE_STREAM_INVENTORY_QA=1` enables the real-FFmpeg tests.
The dedicated workflow runs them on Python 3.11 and 3.12. Normal general CI
skips them so unrelated PRs do not require FFmpeg. Tests cover one valid video,
hidden second video, subtitle track, explicit AAC policy, non-AAC audio,
trusted-hash rejection, malformed probe and privacy-minimized CLI failures.

## Dependencies / owner handoff

- Base: QA17 PR #62 at `009a3ebe6fbb26f267add73406df5e88bae93c41`.
- Lead PR #40 retains production `cinematic_service.py` and media policy.
- PR #64 owns the independent H.264 profile/pixel-format gate; #70/#71 own
  AAC duration/timestamp gates; #73/#83 own source format-tag/chapter privacy.
- This QA does not change the queue (#21), cache acceptance (#23), mobile
  client (#28), lead master assembler (#8/#40) or other helpers' paths.
- Before production integration, decide whether imported masters are allowed,
  whether audio is supported, and how cached SHA-valid masters are revalidated.

**Not verified:** actual model inference, 600-second owner-PC render,
production master with an extra stream, authenticated phone streaming or
physical iPhone playback. Do not interpret synthetic acceptance as any of these.
