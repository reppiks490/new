# QA45 — malformed-row-safe SQLite queue reads (integration candidate, NOT production wired)

**Ownership:** Four new QA45-only files on frozen lead PR #40 (`05c59556d64a808dcc3a8ca96fae5e572c9e446d`). No edits to `cinematic_assembly_jobs.py`, router, lead, other helper branches, ICARUS or automations. Draft; do not merge without lead review.

## Reproduction and repair candidate

QA44 PR #99 demonstrated that one invalid JSON *text* row of kind `video_assembly_job` can cause SQLite's `json_extract(data, '$.status')` to raise `OperationalError: malformed JSON`, blocking unrelated healthy queue claims and startup replay. The QA45 regression first proves the unguarded SQL failure using real in-memory SQLite, then exercises opt-in guarded query functions for all affected queue read families: single-flight running count, FIFO queued selection, startup running scan, per-project active deduplication, global capacity, and project history pagination.

The guarded SQL uses `CASE WHEN json_valid(data)=1 THEN json_extract(...) ELSE NULL END` rather than relying on `WHERE json_valid(data) AND json_extract(...)` short-circuit evaluation. Malformed records are **preserved**, not automatically repaired/deleted. All user project IDs and page parameters remain bound query parameters; query functions do not print payloads, mutate SQLite, or start FFmpeg.

## Lead integration map

- `enqueue_master_assembly`: use `active_project_rows(db, project_id)` and `outstanding_count(db)` *inside its existing `BEGIN IMMEDIATE` transaction*; retain revision/readiness, active idempotency and 32-job cap.
- `_claim_next`: use `running_count(db)` then `next_queued(db)` *inside the same existing `BEGIN IMMEDIATE` transaction*. Never claim a second job if a valid running record exists.
- `recover_assembly_queue`: use `running_rows_for_recovery(db)` inside its existing transaction; retain current failure semantics, but coordinate #63 worker ownership before any multi-process deployment.
- `list_master_assembly_jobs`: use `project_history_page(db, project_id, limit=limit, offset=offset)`; preserve existing authenticated project existence check and response schema.

**Not fixed by this PR:** production calls still use unguarded SQL; valid-JSON records with unexpected shapes, SQLite page corruption, #95 transient status-write orphaned jobs, #94 post-commit dispatch receipts, #56 duplicate worker submissions, #63 process ownership, #23 media acceptance and #40 creative revision binding. These require lead-owned integration tests on the real service/SQLite worker and final full CI. Invalid rows remain private forensic evidence and must not be exposed to mobile/API clients.

**Verification boundaries:** Synthetic SQLite only, no owner database, FFmpeg, model inference, owner-PC rendering, Windows ACL or physical mobile playback. This is a green candidate utility, **not proof of production repair**.
