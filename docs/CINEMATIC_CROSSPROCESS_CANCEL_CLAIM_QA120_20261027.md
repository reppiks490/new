# Character3D QA120 — independent-process cancellation versus worker claim

**Scope:** isolated additive QA-only branch from QA117 #218, frozen parent
`fc2fbad63d25fe5b332e46e3ca3427fedb2fb49a`.
No existing production, queue, media, server, mobile, helper, or other-agent files changed.

## Why this test

QA115 #216 established real independent-process SQLite admission; QA116 #217
established queued replay after process exit; QA117 #218 established
cross-process cancellation followed by restart. Helper 1 QA119 #220 tests
HTTP cancellation versus claim in **threads of one interpreter**.

None of these tests independently establishes that a *different operating-system
process* racing SQLite `_claim_next()` against
`cancel_queued_master_assembly()` cannot both win. QA120 closes that
specific cross-process atomicity acceptance gap.

## Method and exact boundary

Eight fresh disposable SQLite WAL workspaces are seeded with one queued job
each. For each workspace, two distinct Python interpreters signal readiness
through filesystem markers and wait on a common release gate. One calls the
real SQLite `_claim_next()`; the other calls the real SQLite cancellation
transaction. The parent checks durable records and demands **exactly one**
outcome:

- Cancellation wins: no claim, durable `cancelled`, repeat cancellation
  idempotent, and no later claim.
- Claim wins: cancellation reports conflict, durable `running`, then the
  parent performs an explicitly synthetic failed-status cleanup via real CAS.

The test does not demand a particular winner or make probabilistic claims
about exhaustive race coverage. No FFmpeg, actual worker execution,
inference, cloud generation, owner footage, mobile device, or Windows/WSL2
is involved. This is an acceptance test, **not a reproduced production defect
or a production fix**.

## Coordination and remaining release blockers

Master assembly #8; async queue #21; cache/media #23; integration #40.
Helper 1 owns HTTP cancellation privacy/race QA118 #219 and QA119 #220,
and private auth/cache middleware #171/#214. Do not overwrite those files.

QA99 #200 still proves that a second API process can interrupt a *live*
worker; QA114 #215 demonstrates duplicate executor dispatch on idempotent
enqueue. Source audio #201 and denial cache #204 require coordinated
decisions. **Single API process per shared SQLite workspace remains the
supported operational boundary.** A final combined integration SHA needs
full CI and genuine synthetic FFmpeg/FFprobe/decode acceptance before any
release decision.

No merges, deployments, services, owner media/credentials, ICARUS changes,
or ChatGPT automation modifications are authorized.
