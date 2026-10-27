# Character3D QA123 — cross-process private HTTP polling and reconnect acceptance

**Frozen parent:** QA121 draft PR #222 at `4e0ea15399e524a11a94d82d8ffab6078d518b0c`.
**Ownership:** three *new* QA123-only paths (test, isolated workflow, this handoff).
**Policy:** draft, unmerged, no deployment, no owner media, no cloud inference/spend.

## Gap addressed

QA115–QA121 exercise independent-process SQLite admission, cancellation, restart,
claim and FIFO safety. Helper 1 QA118–QA122 owns HTTP cancellation and its
independent-process claim races. This acceptance adds a different boundary:
**the private HTTP polling/history contract used by a reconnecting phone must
observe a queued → running → terminal job that a separate Python interpreter
actually claims and completes through the real SQLite WAL queue.**

Two parametrized outcomes are tested: success with a **synthetic persisted
verified-looking master record** (no MP4 file), and failure with a private
exception sentinel that must be replaced by neutral public diagnostics.
The test checks token rejection, cross-project job isolation, list pagination,
state timestamps, absence of premature master fields, terminal metadata,
and reconnect with a new FastAPI TestClient. Only project-existence lookup
and master assembly are stubbed. HTTP middleware/router, SQLite, worker
claim/status CAS and process isolation are real.

**Important evidence boundary:** This is NOT a real FFmpeg/FFprobe encode,
not actual model inference, not a physical phone/browser test, not proof of
artistic continuity or Windows/WSL2 performance, and not proof of safe
simultaneous API server processes. No production correction is proposed.

## Integration coordination

- Lead master assembly #8; async queue #21; cache/media #23; integration #40.
- Helper 1 #171/#214 owns API auth/no-store; #219/#220/#223 owns HTTP
  cancellation. QA123 does not modify their files or duplicate their tests.
- QA99 #200 demonstrates multi-process startup recovery can invalidate a
  still-live worker; **one API process per shared workspace is required**.
- QA114 #215 duplicate executor dispatch, QA100 #201 source-audio preservation,
  QA103 #204 private-denial no-store, and combined integration remain blockers.
- Dedicated Python 3.11/3.12 workflow plus full general CI must be checked on
  the final PR head / generated merge candidate. A passing mock-assembly test
  does not clear any production or physical-device release gate.

No ICARUS changes, ChatGPT automation changes, force pushes or merges.
