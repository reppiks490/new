# Character3D QA115 — independent-process SQLite admission acceptance

**Scope:** additive QA-only acceptance, draft/unmerged; no shared production or helper files.
**Frozen parent:** QA114 #215 at `638972c33fab4554e977f5cf47f0241744925e7c`.
**Related:** master #8, async queue #21, media/cache #23, integration #40,
Helper 1 #171/#194/#214, QA99 #200, source audio #201, private-denial
cache #204, and duplicate-dispatch QA114 #215.

## Why this test exists

The async master queue uses SQLite WAL with `BEGIN IMMEDIATE` for idempotent
admission and a global outstanding-job cap. Existing concurrency tests exercise
threads in one Python process. QA99 separately demonstrated a **multi-process
worker startup-recovery defect**; passing admission tests must not be mistaken
for safe multi-worker execution.

`tests/test_cinematic_crossprocess_admission_qa115.py` starts four truly
independent Python interpreters against the same disposable SQLite workspace,
waits for all to reach a filesystem start barrier, and checks two admission
contracts:

1. Four identical requests for the same project/revision reuse one queued
   record and return the same durable job ID.
2. Four distinct project requests against a deliberately reduced capacity of
   two admit exactly two and reject two with `AssemblyQueueFull`. No
   over-admission is allowed across interpreter boundaries.

The parent inspects the actual persisted SQLite records after the children
exit. Each child stubs project readiness and substitutes a holding executor
that does not run the worker drain. This is a real cross-process database
admission test, **not** a real multi-process worker or media test.

## Evidence boundary and known defects

This test cannot prove that multiple API processes may safely start,
recover, claim or complete the same master. The application still documents
one local API process. In particular:

- QA99 #200 demonstrates a live worker may be invalidated by another
  process's startup recovery. Requires lead-owned lease/fencing design.
- QA114 #215 demonstrates redundant executor submissions on identical
  retries, including in a single process. This test deliberately does not
  count or execute drain futures.
- QA100 #201 documents silently discarded synthetic source AAC.
- QA103 #204 and Helper 1 #171/#214 own cache denial and Bearer-scheme
  corrections; Helper 1 #194 owns the strict-media integration push gate.
- QA115 uses no FFmpeg, model inference, owner footage, Windows/WSL2
  rendering or physical mobile playback.

## Review and integration requirements

Do not merge this test stack merely because its own CI passes. Preserve the
frozen QA114 base and review the entire accumulated cinematic branch against
canonical `feat/cinematic-orchestrator-v1`. Integrate lead-owned queue and
privacy corrections on one reviewed commit, then verify that **exact commit**
with general CI, strict synthetic FFmpeg media, privacy and HTTP Range tests.
Do not enable cloud generation, paid services or live owner-media access.
