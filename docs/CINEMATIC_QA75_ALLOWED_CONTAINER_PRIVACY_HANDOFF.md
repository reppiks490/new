# Cinematic QA75 — permitted-container nested MP4 privacy acceptance

## Ownership and exact evidence
This is an isolated draft continuation of QA74 #159, frozen at `6034f1da306635c5b5bc5a69e922576cece30e9b`. QA74 had 21 successful workflows and one cancelled QA57 workflow at the initial inspection; that is **not** 22/22 green. QA75 adds its own genuine-media test/workflow and modifies only the opt-in, read-only `tools/cinematic_completed_master_decode_qa54.py`. No production FFmpeg worker, SQLite queue, cache, authenticated streaming, mobile UI or Helper 1 router files are changed.

**Confirmed test-first RED:** exact test-only HEAD `ccbbf613320c0b27a6b5b0e39c5e2c6d29835828`, [QA75 workflow 40265254925](https://github.com/reppiks490/new/actions/runs/40265254925). Python 3.11 job `121386141236` and Python 3.12 job `121386141444` each completed **2 failed / 1 passed**. The two failures were incorrect strict successes for synthetic opaque `priv` children under `moov/udta` and `moov/trak/edts`. The clean control passed. Both modified MP4s FFprobed as H.264, retained 48 frames/24 FPS/two-second timing, fully decoded with genuine FFmpeg and matched their temporary SQLite SHA-256. Legacy decode-only mode also passed. This is an offline privacy-attestation coverage defect, **not** demonstrated remote exploitation or exposure of owner footage.

## Narrow proposed correction
QA75 extends the existing structural allowlist to immediate `udta` and `edts` children. FFmpeg's ordinary `udta/meta` and `edts/elst` remain permitted. Unknown children, nonempty `free` padding, malformed bounds and traversal beyond the 4096-box budget fail strict acceptance. Traversal reads only box headers, checks full child-container coverage, and emits aggregate counts rather than box bytes or owner paths. Existing legacy decode-only behavior is unchanged.

## Limits and acceptance
This is **not** comprehensive MP4 sanitization: `udta/meta` and `edts/elst` payload contents, sample descriptions, compressed video/audio data and other permitted descendants are not fully inspected. Conservative allowlists may reject valid non-FFmpeg muxer output. No inference, owner footage, complete 600-second owner-PC render or physical iPhone playback is claimed.

Review exact-final-HEAD QA75 Python 3.11/3.12, inherited QA54–QA74, general Python/Node/Docker CI, and the branch compare before any merge decision. A queued or cancelled check is not a pass. Keep #161 draft/unmerged until lead #40 coordinates integration with original assembly #8, async #21, cache #23 and Helper 1 #160. No deployment, paid service, owner-media transfer, force push, ICARUS or ChatGPT automation modifications.
