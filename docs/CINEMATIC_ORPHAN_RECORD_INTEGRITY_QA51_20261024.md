# Character3D QA51 — conservative record-integrity gate for orphan-media inventory

## Frozen ancestry and disjoint ownership

Draft QA51 #112 stacks on QA50 #110 at `9a12dc424272d009afd9194c9b3ecd50b340c7bb`, which stacks on QA49 #109 and lead cinematic #40. QA51 changes **only** the existing QA49/QA50-owned read-only inspector and adds QA51-owned tests, workflow, and this handoff. It does not touch production assembly, async queue, UI, other helpers' files, ICARUS, or any ChatGPT automations. Do not merge automatically.

## Reproduced gap

The QA50 inventory properly reports active `video_assembly_job` rows but does not treat structurally invalid `video_job` / `video_master` rows as incomplete visibility. A record with an unknown or non-string status, a `succeeded` video job or `ready` master without an `asset_id`, or an invalid asset ID could coexist with untracked MP4s while `candidate_inventory_not_quiescent` was false. This is a **diagnostic interpretation defect**, not proof of a real owner-PC orphan, and no version of the inspector ever deletes media.

**Test-first CI RED:** [QA51 run 40158855077](https://github.com/reppiks490/new/actions/runs/40158855077) exercised actual temporary SQLite databases on Python 3.11 and 3.12. Both had **12 inherited QA49/QA50 tests passing** and **8 new QA51 parametrized assertions failing as expected**. Seven failures involved missing new counters; one proved the substantive invalid-asset-ID false-quiescence flag. All setup/FFmpeg/pytest steps passed. These are intentionally failing pre-fix assertions, not production failures.

## Minimal correction and privacy

The opt-in offline inspector now reports three additional **aggregate-only** counters: `invalid_video_job_status_rows`, `invalid_video_master_status_rows`, and `invalid_completed_asset_reference_rows`. It treats these, along with existing `invalid_asset_id_count`, as incomplete lineage evidence in `candidate_inventory_not_quiescent`.

Allowed generation-job statuses are `queued`, `running`, `succeeded`, `failed`; a persisted master must be `ready`. An unfinished or failed generation job need not have an output ID, but a succeeded job or ready master must. Invalid JSON, non-object rows, and malformed master-queue rows retain QA49/QA50 handling.

No prompts, IDs, filenames, paths, media bytes, credentials, or private SQL rows are emitted. `safe_to_delete_automatically` stays **false unconditionally**. A false uncertainty flag **does not establish process quiescence**; detached encoders and filesystem races remain unobserved. No cleanup or mutation is introduced.

## Verification requirements and evidence boundaries

Run the strict dedicated QA51 workflow on Python 3.11/3.12, including all QA49 and QA50 tests and their genuine short synthetic FFmpeg H.264 acceptance. Verify full general CI and exact final SHA, and review the diff for ownership isolation before integration. This does **not** test actual model inference, owner footage, a real mid-encoding kill, a 600-second owner-PC render, or physical mobile playback.

Lead review dependencies: #8 master, #21 async queue, #23 cache/media, #40 lead, #63 worker fencing, #95 transient write failures, #99/#100 malformed queue SQL, #102 payload integrity, #106 Docker restart, #109/#110 offline inventory, #111 Helper 1 authenticated real-media Docker QA. All remain separately owned and unmerged unless explicitly authorized.
