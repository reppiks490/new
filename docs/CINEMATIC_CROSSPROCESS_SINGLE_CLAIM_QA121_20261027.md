# Character3D QA121 — single-lane FIFO claim across independent processes

**Frozen parent:** QA120 draft PR #221, commit `20c15706ad4a47505301a0c895c14bec6c15765c`.
**Ownership:** only three new QA121 paths: one test, one dedicated workflow, this handoff.
**Merge policy:** draft; no automatic merge or deployment.

## Specific acceptance gap

QA115 #216 covered independent-process admission; QA116 #217 covered sequential queued restart;
QA117 #218 covered cancellation after restart; QA120 #221 covered a cancellation/claim race.
Helper 1 QA119 #220 owns HTTP cancellation/claim conflicts. None of these directly tests
**several independent processes claiming two already-queued jobs while one assembly lane is available**,
then reclaims the next job after the first terminal transition.

The QA121 test seeds two durable, ordered jobs in a disposable SQLite WAL workspace.
Four independent Python interpreters wait at a filesystem barrier and call the real
`_claim_next()` concurrently. Exactly one must claim the older job; the other three
must get no job. A real SQLite status CAS then marks the first job failed using a
**synthetic test-only terminal transition**. Three *new* interpreters contend for
the second job; again exactly one must claim. A late completion attempt for the first
job must not resurrect it. The test repeats this sequence across four fresh workspaces.

This checks process-level mutual exclusion, FIFO selection, terminal CAS and release
of the assembly lane. It is a **new acceptance test, not evidence of a production defect**.
The test intentionally does not start `_drain`, encode media, execute AI inference,
read owner media, exercise HTTP/mobile, or benchmark Windows/WSL2.

## Coordination / blockers

- Master assembly #8; durable queue #21; cache/media #23; lead integration #40.
- Helper 1 owns #171/#214 (private API), #219/#220 (HTTP cancellation). No shared files changed.
- QA99 #200 still demonstrates that a second API process's startup recovery can
  invalidate a live worker. **Single API process per shared workspace remains required.**
- QA114 #215 reproduces redundant executor submissions on idempotent enqueue.
- QA100 #201 source-audio preservation and QA103 #204 private denial no-store
  require integration decisions.
- The draft QA stack is not the canonical integration branch. Final combined-SHA
  CI, real synthetic FFmpeg media, owner-PC rendering and physical mobile playback
  remain separate release gates.

No merges, cloud generation, spending, credentials, owner footage, ICARUS edits,
or ChatGPT automation changes are part of QA121.
