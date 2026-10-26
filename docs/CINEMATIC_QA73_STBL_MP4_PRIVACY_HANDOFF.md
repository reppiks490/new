# QA73 — completed-master sample-table MP4 privacy handoff

Status: isolated **DRAFT** review candidate; do not merge or deploy.

## Frozen lineage and ownership

- Parent: QA72 #155 at `7b205b149abcd8376b0552290100db04a3dd083b`, with **20/20** exact-commit workflows independently verified successful before starting QA73.
- QA73 PR #156 owns a new test, dedicated CI workflow, this handoff and a narrow change to the existing read-only offline inspector `tools/cinematic_completed_master_decode_qa54.py`.
- No production assembly worker, queue, cache, authenticated asset route, mobile UI, other helper files, owner footage or credentials were modified. Original assembly #8, async #21, cache #23, lead #40 and Helper 1 #154 remain independent.

## Test-first defect

QA73's RED candidate `2aa334a66773c4b29d3a5fa51ae96b67bad87c48` tests genuine disposable FFmpeg H.264/48-frame/24-FPS/2-second MP4s with synthetic private canaries inside `moov/trak/mdia/minf/stbl/free` and `.../uuid`. The media retain valid FFprobe metadata, full video decode and matching temporary SQLite SHA-256; clean and empty `free` controls are included. The Python 3.12 dedicated job in [workflow 40255182773](https://github.com/reppiks490/new/actions/runs/40255182773) confirmed **two incorrect strict successes (2 failed / 2 passed)**. Python 3.11 was still in progress when this note was written; check its actual job outcome before claiming both versions.

## Narrow proposed correction

Read-only inspector traverses immediate `stbl` child box headers with the existing bounded parser, rejecting `uuid`, nonempty `free` and malformed child boundaries while allowing empty padding. It does not read or report payload bytes, and preserves decode-only legacy behavior and aggregate-only strict diagnostics. This is not comprehensive ISO-BMFF sanitization; codec steganography, nested `meta`/`udta`, maliciously unusual container layouts and concurrent file mutation remain out of scope.

## Final acceptance still required

Verify dedicated QA73 Python 3.11 and 3.12, inherited QA54–QA72, and general Python/Node/Docker checks **on the exact final candidate commit**, not on parent or test-first commits. Any unfinished or failing workflow is a blocker to calling the proposal fully green.

Genuine synthetic FFmpeg media and temporary SQLite do **not** prove actual model inference, owner footage, complete 600-second owner-PC render, physical phone playback, production multi-worker crash safety or deployed cloud behavior. No merges, deployments, purchases, paid generation, secrets, automation edits or ICARUS changes are authorized.
