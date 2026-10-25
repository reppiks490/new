# Cinematic QA71 — nested mdia MP4 privacy handoff

**Status:** DRAFT; no merge, deployment, cloud generation, or owner-media access.
**Frozen parent:** QA70 #150 `26f181f3ef189dd42a31998456bba1946f1bd20c`.
**Ownership:** new QA71 real-media test, workflow, handoff; narrow change to the existing **offline read-only** strict master inspector only. Production master service, queues, cache, phone UI and concurrent Helper 1 files remain untouched.

## Reproduced defect

The QA70 strict inspector checked top-level MP4 boxes, immediate `moov` children and immediate `moov/trak` children. It did not inspect `moov/trak/mdia` children. Genuine disposable FFmpeg libx264 H.264 MP4s containing a synthetic private canary in either `mdia/free` or `mdia/uuid` passed FFprobe metadata checks, full video decode, 48-frame/24-FPS timing and matching persisted SQLite SHA-256, and incorrectly passed strict privacy attestation.

Test-first [QA71 workflow 40245261666](https://github.com/reppiks490/new/actions/runs/40245261666) completed **FAILURE as expected on Python 3.11 and 3.12**: two false strict successes, two passing controls on each. This is a local offline acceptance bypass, **not** evidence of remote exploitation or real owner-data exposure.

## Proposed correction and limits

Strict mode now walks bounded `mdia` immediate-child box headers and rejects nonempty `free`, any `uuid`, and malformed box bounds. It reads no private box payloads, reports aggregate anomaly counts only, and preserves decode-only compatibility. The clean and empty-`free` controls must continue passing.

This is **not** complete recursive ISO-BMFF sanitization; deeper `mdia/minf`, `stbl`, `meta`, sample tables and encoded video/audio content are outside the current guarantee. Source provenance, crash-safe production queueing, actual model inference, 600-second owner-PC rendering and physical mobile playback are separate validation requirements.

## Acceptance

Review the dedicated QA71 real FFmpeg test, Python 3.11/3.12 workflow, inherited QA54–QA70 workflows and general CI on the **exact final commit**. A queued or in-progress workflow is not a pass. Lead #40 must decide integration explicitly; no automatic merge.
