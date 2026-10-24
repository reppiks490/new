# QA42 — live cinematic master queue liveness after a transient status-write error

**Status:** Isolated, test-first, expected-red regression; no production remediation or deployment.  
**Parent:** draft lead PR #40, exact `05c59556d64a808dcc3a8ca96fae5e572c9e446d`.  
**Related:** #8 master assembly, #21 async queue, #23 cache/media validation, #56 duplicate dispatch, #63 second-worker startup recovery, #91 partial shot-batch receipt, #94 post-commit dispatch receipt.

## Source-backed failure window

In `app/video/cinematic_assembly_jobs.py`, `_drain()` claims a job by persisting `running` and calls `_execute_one()`. Although `_execute_one()` catches exceptions from `assemble_project_master()`, it does not guard the subsequent `_store_status()` database update against an unexpected write failure. If that status update raises, the `_drain` executor future exits, leaving a durable `running` row. A subsequent healthy `_drain()` calls `_claim_next()`, which sees *any* running row and refuses to claim the next queued job. Startup recovery marks running rows failed, but no same-process lease/watchdog or reconciliation is present in the inspected frozen head.

This is a **fault-injection liveness contract**, not evidence that a real owner's SQLite database failed. A persistent full disk or database outage cannot be cured by an in-process retry. The strict test instead simulates one *transient* write failure and then restores healthy writes.

## Evidence and verification protocol

- Two distinct project IDs enqueue two jobs into real temporary SQLite storage, using the actual queue admission and claim functions. The executor is held; no subprocess runs.
- Control: a synthetic encoder exception is caught and both jobs become `failed`; ordinary draining proceeds.
- Strict QA: one `_store_status` call raises an injected `OSError` after the first job has been claimed; the fault clears; a second drain is explicitly attempted without restarting the API. It requires the orphaned `running` claim to be reconciled and the second job to reach a terminal state.
- The frozen implementation is expected to leave the first job `running` and the second `queued`. Dedicated CI enables the strict contract on Python 3.11 and 3.12; ordinary CI skips the expected-red case to avoid misreporting a production fix.
- Do not interpret a green general matrix as proof that the strict defect was repaired. Inspect both exact-final-commit workflow conclusions and assertion output.

## Lead-owned remediation decision

Choose an explicit single-process liveness policy: claim leases/heartbeat with safe fencing, or durable worker-exception reconciliation with bounded retry. Never re-execute an active FFmpeg job merely because its heartbeat is late. Preserve SQLite CAS, one-running-job semantics, privacy-safe errors, idempotency, queue ordering and restart safety. Reconcile with #63 (concurrent process recovery) and #56 (duplicate futures); a naive retry loop or unconditional `running` reset risks duplicate encodes and orphan master publication. No existing production/agent-owned files are edited by QA42.

**Evidence limits:** Actual SQLite records and injected Python exceptions, not real FFmpeg media, model inference, owner-PC 600-second rendering, physical phone playback, owner media or credentials. No cloud generation, spending, deployment, merge or automation changes.
