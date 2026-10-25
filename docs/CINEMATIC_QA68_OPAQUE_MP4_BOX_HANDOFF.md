# QA68 — offline strict cinematic master opaque-box privacy acceptance

**Scope:** Draft, read-only, owner-selected quiescent workspace. Stacked on QA67 #143, not a production master-assembly change. No automatic merge, deployment, file mutation, owner-media processing, inference, cloud services, or paid APIs.

## Reproduction

Disposable real FFmpeg/libx264 H.264 MP4, 48 frames at 24 FPS (2 seconds), temporary SQLite record with the *actual* SHA-256 of each synthetic MP4. Appending a syntactically valid top-level `free` atom containing `QA68_PRIVATE_CANARY_SYNTHETIC`, or a `uuid` atom with a 16-byte user type and the same canary, leaves FFprobe's visible streams/tags/chapters, full video decode, timing and persisted hash correct. Prior strict acceptance did not inventory these opaque boxes and returned success. The test-first QA68 run is [40231530248](https://github.com/reppiks490/new/actions/runs/40231530248): Python 3.11 reproduced the two intended incorrect-success failures (plus one expected missing-counter failure on the clean control); check the run for other job conclusions.

## Narrow proposed gate

`tools/cinematic_completed_master_decode_qa54.py` now walks **top-level** ISO-BMFF box headers in constant memory and accepts the FFmpeg-master envelope of one `ftyp`, one `moov`, one `mdat`, and optional **empty** `free` boxes. Rejects nonempty `free`, `uuid`, unknown top-level boxes, duplicate required boxes, malformed box sizes, or trailing malformed bytes. Distinguishes anomalies from filesystem-unattested reads. Reports aggregate counts only; never outputs box content, media paths, hashes, prompts or decoder stderr. The opt-in strict exit gate incorporates the new counts; legacy decode-only mode retains its prior acceptance behavior. The scanner reads headers only and does not delete media.

## Boundaries and integration risks

This is **not** a general MP4 parser, nested atom sanitizer, codec payload scanner, steganography defense, Windows ACL audit, or proof that owner footage is private. Some otherwise valid MP4s with extra top-level atoms or nonempty padding will be conservatively rejected; do not silently relax this without a reviewed, explicit delivery contract. A matching SHA only proves equality to the recorded bytes, not safety of those bytes. A quiescent owner-selected workspace is required; no multi-writer filesystem race guarantee is claimed.

Lead #40 and owners of #8, #21, #23 must review integration. Helper 1 #142/#144/#145 owns separate source/cache/output POSIX permissions and was not modified. Actual 600-second owner-PC rendering, real model inference and physical mobile playback remain unverified. Require final exact-head Python 3.11/3.12 dedicated FFmpeg QA, inherited QA54–QA67 compatibility and general CI before review.
