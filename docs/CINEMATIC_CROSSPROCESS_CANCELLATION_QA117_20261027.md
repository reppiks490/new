# Character3D QA117 — independent-process cancellation and restart acceptance

**Scope:** additive QA-only, draft and unmerged. Frozen QA116 parent PR #217,
commit `3976be4412aa03055d15d3f33c10358b01f2753a`.
No existing production, queue, media, server, helper, mobile, or owner files modified.

## Reason for this acceptance

QA115 #216 established cross-process SQLite queue admission. QA116 #217 established
queued-job replay after an API process exits. Neither proved that a cancellation
made by a *different* process remains terminal when a later process calls startup
recovery, nor that an unrelated project's cancellation request cannot change
another project's queued work.

## Cases and limits

Two parameterized tests use three **independent Python interpreters** and one
disposable **real SQLite WAL** workspace per case:

1. First interpreter enqueues a ready synthetic project into SQLite with a
   holding executor; second interpreter cancels the queued job and repeats
   cancellation idempotently; third interpreter calls real
   `recover_assembly_queue()` twice. Assert no assembly callback, no master
   metadata record, one durable `cancelled` job, and unchanged job identity.
2. A foreign project ID attempts cancellation and receives `KeyError`
   without modifying the job. The third interpreter then recovers and
   completes exactly one synthetic master, verifying that denial does not
   destroy another project's queued work.

SQLite transaction, cancellation, claim, recovery, and terminal updates are
real application code. Project readiness and executor are mocked; the
`assemble_project_master` callback and verified-looking master metadata are
**synthetic test doubles**. This is not genuine FFmpeg media, model inference,
owner-PC/WSL2, real iPhone/mobile playback, or a simultaneous worker race.

## Integration dependencies

Master #8, async queue #21, cache/media #23, integration #40.
QA99 #200 still proves live multi-process worker recovery is unsafe.
QA100 #201 source AAC policy remains undecided; QA103 #204 cache-denial
`no-store` and Helper 1 #171/#214 authentication need coordinated integration.
QA114 #215 redundant duplicate dispatch remains unresolved.

The canonical integration branch must receive a separately verified combined
commit and strict real-media CI before release. Until lease/fencing is
implemented, operate only one API process per SQLite workspace. Never merge
this stacked QA draft automatically.

No paid/cloud generation, owner media or credentials, deployments, force
pushes, ICARUS edits or ChatGPT automation changes are involved.
