# Character3D QA114 — idempotent queue dispatch amplification

**Scope:** draft, QA-owned test and handoff only; no queue/server/helper production edits.
**Frozen parent:** QA112 #213, `e8c448385ef0d7c7df67bae12a0c0528ccbf297c`.
**Related:** master #8, async queue #21, cache/media #23, lead integration #40,
multi-process recovery #200, source-audio policy #201, private-denial #204,
Bearer regression #213 and Helper 1 production correction #214.

## Code-level finding

In `app/video/cinematic_assembly_jobs.py`, `enqueue_master_assembly`
serializes the SQLite admission transaction and correctly returns the same
queued/running record for an identical project revision and FFmpeg selection.
After leaving the transaction it **unconditionally** calls `_dispatch()`.
That function calls `assembly_pool.submit(_drain)` for every request, even
when no new job was inserted. The pool has one worker, but its submitted
future backlog is not capped by the durable `_MAX_OUTSTANDING=32` job limit.

The pre-existing `tests/test_cinematic_assembly_queue.py` explicitly
expects two executor submissions for two idempotent requests. That assertion
must be reviewed together with any production correction; do not silently
rewrite the concurrent owner's queue files in this QA branch.

## Reproduction contract

`tests/test_cinematic_idempotent_dispatch_qa114.py` uses a disposable
SQLite workspace, a fake ready project and a holding executor. Sixty-four
identical calls return the same job ID and exactly one persisted queued
record, then the test requires at most one scheduled drain. The current
implementation schedules 64. The test does not execute those futures and
does **not** measure actual memory exhaustion, CPU saturation, media
rendering, owner hardware, or remote attack feasibility. It isolates
an executor-admission amplification mechanism under authenticated retries.

## Safe correction requirements for lead review

A future lead-owned fix should coalesce redundant wakeups while preserving:
- One durable job for identical requests and bounded distinct job admission.
- A wakeup after a newly queued job, a worker failure, or a restart; never
  leave persisted work stranded because a stale in-process flag says busy.
- A race-free handoff between the draining worker's final empty-queue check
  and the next enqueuer, including callback/submit failures.
- Cross-process worker lease/fencing (#200) before claiming multi-worker
  safety. An in-process lock alone does not fix multi-process recovery.
- Existing cancellation, polling, timestamp, privacy, and queue-full
  contracts. Update the older two-submissions test deliberately, with an
  explanatory change, once a correct dispatch design is reviewed.

## Evidence boundary and integration

This is mock-executor/real-SQLite QA, not real FFmpeg, model inference,
physical iPhone playback or Windows/WSL2 performance. A strict expected
failure, if used after RED reproduction, records an unresolved defect; it
does not fix it. All branches are draft/unmerged. Run final CI on the exact
reviewed integration commit, including the opt-in genuine synthetic media
checks. Do not merge/deploy/spend/activate cloud generation or touch owner
media, credentials, ICARUS, or ChatGPT automations.
