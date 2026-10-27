# Character3D QA116 — queued master assembly replay across process exit

**Scope:** additive QA-only acceptance, isolated draft/unmerged; no production, queue,
media, server, mobile or other helper-owned paths changed.

**Frozen parent:** QA115 PR #216 at `19121569aac0bab6046cf59ac64ec463d7321708`.
**Related:** master #8, async queue #21, cache/media #23, integration #40,
Helper 1 #171/#194/#214, live-worker recovery QA99 #200, source audio #201,
cache-denial QA103 #204, dispatch amplification QA114 #215, admission QA115 #216.

## Acceptance contract and scope

QA115 proves four *simultaneous* interpreters can atomically admit distinct
or idempotent queued records to one SQLite WAL workspace, but intentionally
does not execute workers. QA116 adds a complementary *sequential process
restart* contract for the durable queue:

1. An independent interpreter admits one synthetic-ready project/revision to
   real SQLite. Two modes are tested: a holding executor that accepts but
   never runs a drain, and an executor whose `submit` raises a private
   diagnostic exception. The latter must expose only the neutral public
   message while leaving exactly one queued durable record.
2. The first interpreter exits. A **new interpreter** calls the real
   `recover_assembly_queue()`, uses the real SQLite `_claim_next()`,
   `_store_status()`, and `_drain()`, and completes a **stubbed**
   `assemble_project_master()` that persists synthetic, probe-shaped
   metadata. The second recovery call must not execute it again.
3. The parent checks actual SQLite after both children exit: one terminal
   job and one master metadata record, with no private executor diagnostic
   in the public response or durable job payload.

**Critical evidence boundary:** The master result is a *test double*. Its
`probe_metadata_verified` flag is synthetic; no media is created or
validated. This is real independent-process SQLite replay and state-machine
acceptance, **not** actual FFmpeg rendering, real artifact verification,
model inference, owner-PC readiness, or physical mobile playback.

## Expected interpretation

A green result shows a queued record survives a clean process exit and can
be drained by a later process, including after executor submission rejection.
It does **not** establish safe simultaneous API workers. QA99 #200 proves
that a second process starting while another owns a live `running` record
can incorrectly fail that live job. Until lease/fencing correction, retain
the **single API process per SQLite workspace** operational restriction.

QA114 #215's redundant executor submissions remain unresolved; this test
does not coalesce them. QA100 #201 source AAC policy, QA103 #204 denial
`no-store`, Helper 1 #214 Bearer hardening and combined integration CI
also remain separate.

## Integration and verification

Dedicated `cinematic-crossprocess-queued-replay-qa116.yml` executes the two
process-exit cases on Python 3.11 and 3.12, including on changes to the
queue/storage/request modules and on canonical cinematic branch pushes.
General CI must also pass on the **exact proposed head**. Do not treat a
passing stacked draft as proof that the canonical cinematic integration
branch includes these tests or corrections. The lead must reconcile all
stacked changes and verify the resulting combined commit, including strict
real synthetic FFmpeg and authenticated private Range tests.

No owner media/credentials, paid/cloud generation, deployments, merges,
force pushes, ICARUS repositories or ChatGPT automations are involved.
