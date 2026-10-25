# QA64 — Completed-master AAC payload decode integrity (draft)

## Frozen scope and ownership

- Parent: QA63 PR #135, commit `5017fd4bc96caec789dd97ad7b91535f6487c759`.
- Proposed branch: `chatgpt/cinematic-master-audio-decode-qa64-20261025`.
- Changes: new QA64 test, workflow and this handoff; narrow change only in our existing offline `tools/cinematic_completed_master_decode_qa54.py`.
- No production master assembly, queue, cache, source-snapshot, mobile UI, cloud, ICARUS, owner media, credentials, or automation edits. Do not auto-merge or deploy.

## Test-first genuine media reproduction

A disposable 2-second 48-frame H.264 video and full-length AAC-LC soundtrack were generated with real FFmpeg. FFprobe selected twenty *audio packet payload* byte ranges, replaced their contents without altering MP4 atoms or the video stream, and independently verified that the resulting file retained:

- AAC-LC stream metadata with aligned start/end and 2-second container duration;
- successfully decoded H.264 video;
- 48-frame / 24-fps delivery timing;
- an updated, matching SQLite persisted SHA-256.

The corrupted AAC produces real decoder errors. Some FFmpeg versions exit nonzero; other versions log errors at `-v error` while returning zero. The regression requires **neither a nonzero process code nor an empty error log to be ignored**. The original strict inspector did not decode AAC at all, so it returned exit 0 for the corrupted master.

Test-first **RED**: GitHub Actions run [40212937099](https://github.com/reppiks490/new/actions/runs/40212937099), Python 3.11 and 3.12: three expected failures each — clean/video-only controls lacked new aggregate counters; corrupted AAC had strict exit 0 instead of required 1. Earlier fixture attempts [40212647263](https://github.com/reppiks490/new/actions/runs/40212647263) and [40212797784](https://github.com/reppiks490/new/actions/runs/40212797784) exposed FFmpeg-version error-concealment differences and were refined before this valid RED.

## Proposed narrow correction

For a single optional audio stream, decode all AAC audio locally to FFmpeg's null sink and treat either a nonzero exit or any `-v error` diagnostic as an anomaly. The temporary stderr sink is private and closed without logging its contents; output remains aggregate counts only. Audio decoder execution failure/timeout is **unattested**, never silently accepted. The strict `--require-integrity` exit now also checks `audio_decode_anomaly_count` and `audio_decode_unattested_count`; video-only masters remain allowed and legacy decode-only CLI behavior remains unchanged.

This is an **offline/quiescent owner-workspace audit**, not a live worker gate. It proves neither perceptual audio quality, lip-sync, source lineage, complete 600-second rendering, actual model inference nor physical mobile playback.

## Verification and integration

Final exact-HEAD QA64 and inherited CI results must be read from PR #137; never infer green from test-first RED or from a different SHA. Lead #40 owns production integration; Helper 1 #136 owns source snapshot fencing; master #8, async #21 and cache/media #23 remain separate and untouched.
