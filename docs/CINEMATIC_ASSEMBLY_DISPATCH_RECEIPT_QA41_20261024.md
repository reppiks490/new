# QA41 — Durable master-assembly receipt when worker dispatch fails

Date: 2026-10-24. Repository: `reppiks490/new`. **Draft / test-first / no production behavior change.**

## Exact ownership and scope

Frozen lead integration base: PR #40, `05c59556d64a808dcc3a8ca96fae5e572c9e446d`.
Dedicated branch: `chatgpt/cinematic-assembly-dispatch-receipt-qa41-20261024`.
Three QA41-only additive paths: test, dedicated CI, this document.
No changes to #8 master assembler, #21 async queue, #23 cache/media, #40 lead, #56 dispatch coalescing, #91 shot-batch partial recovery, or any concurrent helper's files.

## Source-backed failure path and expected contract

1. `enqueue_master_assembly()` in `app/video/cinematic_assembly_jobs.py` commits a new `video_assembly_job` row under `BEGIN IMMEDIATE`, exits the transaction, then invokes `_dispatch()`.
2. If the executor's `submit()` raises `RuntimeError` (e.g., a shutdown race), `_dispatch()` raises `RuntimeError("Assembly queued, but local worker is unavailable")`. The already committed job remains `queued`.
3. `queue_cinematic_master_assembly()` in `app/video/router.py` converts that exception into a generic HTTP 503 with no authoritative job ID. The client cannot tell from the response alone whether a job was durably committed. An authenticated list endpoint exists, but relying on list/history discovery is weaker than returning the committed receipt, especially during mobile disconnects or concurrent requests.
4. The existing idempotent retry should reuse the same active job and attempt dispatch again. A fix must **not** roll back, duplicate, or strand the committed work.

QA41 includes a **green control** using real temporary SQLite storage, a rejecting executor, and a later accepting held executor: exactly one queued job remains and the duplicate retry returns the same ID.

The strict **expected-red API contract** uses an authenticated FastAPI TestClient with the same SQLite queue and a rejecting executor. It accepts either HTTP 202 with the committed `id` or HTTP 503 with a structured `detail.job_id` (and expects no screenplay/token leakage). It requires the returned ID to match the sole durable queue row. The current generic HTTP 503 has no ID, so this contract is expected to fail until a lead-owned remediation.

General CI skips only the strict expected-red test; the dedicated Python 3.11/3.12 workflow sets `CINEMATIC_REQUIRE_ASSEMBLY_DISPATCH_RECEIPT_QA41=1`. Treat a red strict workflow as a reproduced unmet contract, **not** as passing CI.

## Integration recommendation

The lead and async-queue owner should decide an explicit, privacy-safe commit/dispatch response contract. Prefer returning the committed job ID and a neutral `queued` / `worker_unavailable` state even when scheduling the in-process executor fails, with clear client retry/poll guidance. Preserve HTTP auth, project-scoped lookup, idempotent reuse, cancellation/claim CAS, bounded outstanding queue, and restart replay. Do not introduce an unbounded executor submission loop: #56 independently demonstrates dispatch-future amplification. #91 covers *shot batch* partial scheduling, not this *master-assembly* post-commit dispatch window.

No automatic merge or deployment. Do not expose local paths, private screenplay, source media, credentials, or detailed worker exceptions.

## Evidence boundaries / remaining gates

These tests use **real SQLite persistence**, an **authenticated application API**, and **synthetic held/rejecting executor fault injection**. The MP4 fixture is only a signature-level stub to exercise existing readiness behavior; it is **not decodable media**. No FFmpeg encoding, model inference, owner-PC 600-second render, mobile hardware playback, or paid/cloud generation was run. This QA does not address prior source-decode admission #92, image admission #93, long-form FFmpeg limits #79-81, private filesystem modes #86, or mobile transport and display acceptance.

CI links, exact final SHA, and outcomes should be appended to PR conversation after GitHub Actions completes. Do not infer a pass from the existence of the workflow.
