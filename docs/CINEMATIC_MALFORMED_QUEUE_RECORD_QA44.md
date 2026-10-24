# QA44 — Malformed cinematic master-queue record isolation (draft, unmerged)

## Frozen scope and ownership

Parent: lead cinematic integration PR #40, exact commit
`05c59556d64a808dcc3a8ca96fae5e572c9e446d`.
This branch adds only the QA44 regression, its dedicated workflow and this handoff.
No lead, helper, production, ICARUS or automation files are edited.

Related: #8 master assembly; #21 durable queue; #23 media acceptance;
#40 integration; #56 coalesced dispatch; #63 multi-worker startup;
#94 post-commit receipt; #95 live status-write liveness; #97 offline queue health.

## Source-backed failure mode

`app/video/cinematic_assembly_jobs.py` queries SQLite `records.data` with
`json_extract(data,'$.status')` in `_claim_next()` and
`recover_assembly_queue()` (also in admission/history). A single
syntactically malformed JSON **text value** stored under kind
`video_assembly_job` makes SQLite raise `OperationalError: malformed JSON`.
A separate healthy queued record can therefore be unclaimable, and startup
replay can abort before scheduling work.

This was independently reproduced with a real in-memory SQLite engine using
one malformed JSON text row and one valid queued row. The added tests reproduce
the same contract against the repository's actual SQLite storage and queue
module. Ordinary CI skips two *expected-red* contract assertions; dedicated
QA44 runs them under both Python 3.11 and 3.12. **Do not merge a red-only
test as though it were a production fix.**

This is not evidence that the owner's SQLite database contains malformed
records. SQLite transactions and `json.dumps` ordinarily produce valid JSON;
the risk applies to preexisting/migrated, externally modified or otherwise
invalid record text, **not** an assumed normal worker crash. The test does not
simulate corrupted SQLite database pages.

## Proposed lead-owned remediation (not implemented here)

1. Fail closed per malformed row without deleting or automatically rewriting
   it. A `CASE WHEN json_valid(data) THEN json_extract(...) ELSE NULL END`
   expression is a candidate; test on the target SQLite versions rather than
   assuming predicate evaluation order in a `WHERE` clause.
2. Ensure all queue admission, claim, cancel, history and recovery SQL paths
   tolerate or explicitly quarantine invalid JSON while preserving healthy
   FIFO order, transaction atomicity, capacity semantics and project isolation.
3. Emit a **private, sanitized** corruption warning with counts, not record
   JSON, filenames, prompts, project IDs or credentials. QA43's read-only
   inspector may help operators diagnose this without altering records.
4. Keep single-flight FFmpeg and worker fencing guarantees; do not use an
   unbounded auto-retry or a blanket status reset to repair malformed rows.
5. Re-run the strict QA44 tests, #95 liveness tests, #21 durable queue tests,
   #23 real-media tests and complete Python/Node/Docker CI on the final
   integrated commit.

## Verification boundaries

The control and regressions use real synthetic SQLite/WAL storage. They do not
encode or decode FFmpeg media, run any AI model, read owner footage, verify a
600-second owner-PC render, or exercise a physical phone. A green general CI
does **not** mean the strict QA44 contract is fixed; expected-red dedicated CI
must be interpreted separately.

## Final CI evidence

Pending exact-head workflow verification; append the actual SHA, job outcomes
and run URLs in PR comments, not an invented green claim.
