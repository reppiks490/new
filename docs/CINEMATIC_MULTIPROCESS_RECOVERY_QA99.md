# QA99 — multi-process cinematic assembly recovery blocker

**Scope:** evidence-only, no production change. Frozen parent: QA98 PR #199,
`36a503d42095feec7a781d3e3cbabf102c343ae5`.
Draft QA99 PR #200 is **not a multi-worker fix** and must not be merged as one.

## Concrete defect and test-first evidence

`app/video/cinematic_assembly_jobs.py` explicitly says it is designed for
**one local API server process**. Its `_claim_next()` serializes claims with
SQLite `BEGIN IMMEDIATE`, but `recover_assembly_queue()` unconditionally
changes **every** `running` record to `failed / Interrupted` on startup.
The original worker's later `_store_status()` only updates a record whose
status is still `running`. A second API process starting while the first
is encoding can therefore invalidate a still-live worker and discard its
terminal result, even though the worker process remains alive.

The new test `tests/test_cinematic_multiprocess_recovery_qa99.py` launches
a separate real Python OS process to claim a synthetic queued record in
a temporary SQLite WAL database. The claimant stays alive and blocked while
the parent simulates another API process startup. The test verifies that a
second claim is refused, then invokes the real startup recovery and releases
the original claimant. A separate positive control exits its claimant before
recovery to verify that orphaned records are failed closed.

**Test-first RED:** commit `a7aee1508f6aba1daa2ee1caa83a87033d7ac334`,
[general CI run 40445137078](https://github.com/reppiks490/new/actions/runs/40445137078).
Python 3.12 reproduced the specific failure:
`test_second_process_startup_does_not_interrupt_live_worker` expected
`interrupted == 0` but received `1`; **1 failed, 839 passed, 25 skipped**.
The exited-worker positive control passed. This is a real cross-process
SQLite state transition using **synthetic records**; no FFmpeg encoding,
model inference, private footage, owner-PC process or mobile device ran.

After the red reproduction, the negative control is marked **strict xfail
limited to the dedicated LiveWorkerRecoveryConflict exception**. This
keeps unrelated test failures visible and makes an unexpected successful
recovery a strict XPASS failure until the expected-failure marker is removed.
An xfail is **an unresolved production defect**, not a fix or a passed
multi-process acceptance test.

## Operational constraint until corrected

Run **one** API server process for a shared cinematic SQLite workspace.
Do not start multiple Uvicorn/Gunicorn workers against the same database
and assume durable queue recovery is safe. Concurrent client requests
to a single API process are a different scenario and are not this defect.
An extra server process can interrupt an existing encode and leave an
orphaned artifact even if the original FFmpeg subprocess continues.

## Proposed lead-owned implementation and acceptance

1. Establish durable, unguessable worker ownership and a bounded lease or
   heartbeat in the SQLite claim transaction; do not rely solely on PID
   existence or process-local memory (PID reuse and Windows semantics).
2. Fence terminal writes with the claim token/epoch so an old worker cannot
   publish after ownership changes. A second process startup must preserve
   a **live** lease; expired/crashed ownership must fail closed or be
   explicitly reclaimed under a serialized transaction.
3. Ensure recovery cannot dispatch the same encode twice. Define restart,
   lease expiry, stale revision, manual retry and cancellation semantics
   before changing the existing queue contract.
4. Re-run both process-level tests without xfail; then test actual concurrent
   FFmpeg assembly, abrupt process death, restart, disk errors, Windows
   SQLite locking, owner-PC behavior, and authenticated mobile polling.
5. Review with the owners of #8 (master), #21 (async queue), #23
   (cache/media), #40 (integration), #194 (strict private Range), and
   #199 (600-second integration push) before combined-SHA CI.

No owner media, credentials, paid/cloud generation, deployment, merges,
force pushes, ICARUS repositories or ChatGPT automations were touched.
