# Character3D QA50 — Master queue visibility in private orphan-media inventory

## Exact ownership and dependency

This draft stacks on QA49 #109 at `f214e000f55dd5fb49554281e8a2f2d538396207`, which stacks on lead cinematic integration #40 at `05c59556d64a808dcc3a8ca96fae5e572c9e446d`. Only the **QA49-owned read-only utility** is amended, alongside two new QA50-owned files (test and workflow) and this document. The #109 branch itself is not updated. No production assembly worker, UI, media, cloud provider, credentials or other helper-owned paths are changed.

## Reproduced failure and correction

The async master queue persists rows under `video_assembly_job` (#21/#40), whereas the QA49 offline candidate inventory read only `video_job` and `video_master`. A `running` assembly may be writing a UUID MP4 before a `video_master` row is saved. QA49 could count that MP4 as untracked without detecting the active master worker. This is an **audit interpretation gap**, not evidence of an owner-PC incident, and QA49 has never authorized automatic deletion.

Before the fix, dedicated CI QA50 run **40155275048** failed exactly four new regression assertions on **both Python 3.11 and 3.12**, with all eight prior QA49 tests passing. The failures were missing master queue activity fields and ignored malformed master queue rows, not test setup failures.

The additive correction now:
- Reads all three relevant SQLite record kinds, including `video_assembly_job`.
- Reports **aggregate-only** pending/running master assembly count.
- Reports malformed and unrecognized master queue records as uncertainty, rather than silently treating the inventory as quiet.
- Preserves prior media reference counts: queue receipts are **not** treated as independent `video_master` or `video_job` asset evidence.
- Adds `candidate_inventory_not_quiescent` as a conservative signal when a known queue/generation job is active or record visibility is incomplete.
- Retains `safe_to_delete_automatically: false` unconditionally.

The indicator is **not a process fence or a proof of quiescence**. A detached FFmpeg process, new job arriving after the read-only snapshot, or a process not represented in SQLite may still be writing media. No automatic repair, deletion, or clean-up is proposed.

## Acceptance and integration

Run the strict Python 3.11/3.12 QA50 workflow against both the original QA49 suite (which includes one real synthetic FFmpeg MP4) and four synthetic SQLite master queue regressions. Check full general CI at the **final** commit before review. Preserve QA49's path/ID/prompt/credential privacy guarantee, WAL read-only access, symlink safety and non-mutating semantics.

For the lead, this is a **diagnostic safety correction only**. It does not solve #95 live worker write-failure recovery, #99 malformed production queue queries, #100 guarded-query integration, #102 structurally invalid active rows, #106 actual mid-encode crash proof, #109 safe orphan handling, or #63 multi-worker fencing. Coordinate with #21 and #23; do not merge divergent histories automatically.

## Evidence boundaries

Tests use synthetic SQLite rows, a synthetic short FFmpeg source in the inherited QA49 suite, and no real owner database, media, credentials, model inference, cloud generation, 600-second render, or physical phone playback. No external FFmpeg process enumeration or mid-encoding SIGKILL was performed.
