# QA72 — strict completed-master MP4 minf privacy handoff

Status: isolated **DRAFT** proposal for lead review; no merge/deployment.

## Frozen lineage and ownership

- Parent: QA71 draft #152 at `84f8113bd50ea97970e7b60b44d2fe6922d7027e`. Before QA72 work, all **19** parent final-commit workflow runs returned SUCCESS.
- QA72 PR #155 owns only its new test, dedicated workflow, this handoff and a narrow change to `tools/cinematic_completed_master_decode_qa54.py`.
- No production assembly worker, async queue, cache, mobile UI, router, Helper 1 files, owner media or credentials changed. Original assembly #8, async #21, cache #23 and lead integration #40 remain independent.

## Confirmed test-first defect

[QA72 RED workflow 40250442389](https://github.com/reppiks490/new/actions/runs/40250442389) completed FAILURE on **Python 3.11 and 3.12**. Each ran four genuine synthetic FFmpeg H.264 media cases: clean and empty `free` controls passed; two opaque `moov/trak/mdia/minf/free` and `.../uuid` canary cases failed because strict inspection incorrectly returned exit code zero. Fixtures were 48 frames at 24 FPS (2 s), FFprobe metadata remained clean, video fully decoded, and temporary SQLite stored the correct media SHA-256. The canary did not appear in FFprobe JSON or inspector output. This proves a local offline strict-inspector gap, not a remote exploit or owner-footage disclosure.

## Narrow correction and proof requirements

Read-only `minf` immediate-child box-header traversal reuses bounded loops, checks child lengths against parent limits, rejects any `uuid` or nonempty `free` payload, and preserves empty padding. Existing aggregate-only anomaly counters and legacy decode-only compatibility remain unchanged. The code reads only box headers and does not publish private paths, payloads, metadata values or hashes.

**Final-head CI must be independently checked** for dedicated QA72 Python 3.11/3.12, inherited QA54–QA71 workflows, and general Python/Node/Docker CI. A test-first red result and parent green runs are not evidence that this correction passes.

## Remaining limitations

Not comprehensive ISO-BMFF sanitization: deeper `stbl`, `meta`, `udta`, codec steganography, and complex box variants remain outside this check. Offline inspection requires a quiescent workspace; it is not production ingress sanitization. No actual AI model inference, owner footage, 600-second owner-PC render, mobile-device playback, crash-safe multiworker proof, deployment or cloud generation occurred. Do not merge without lead review and final-commit green verification.
