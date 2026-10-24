# Character3D QA38 — durable batch partial-failure recovery (2026-10-24)

**Status: isolated, test-first draft; production remains unchanged.**
**Frozen parent:** cinematic lead integration [#40](https://github.com/reppiks490/new/pull/40), commit `05c59556d64a808dcc3a8ca96fae5e572c9e446d`.
**Owned files:** `tests/test_cinematic_batch_partial_recovery_qa38.py`, `.github/workflows/cinematic-batch-partial-recovery-qa38.yml`, and this handoff. Do not merge automatically or overwrite lead-owned `app/video/cinematic_service.py`, `app/video/cinematic_rendering.py` or `app/video/jobs.py`.

## Specific correctness hypothesis

`render_project_missing()` calls `render_shot()` once per eligible shot. Each successful shot immediately creates a durable job and advances the project's revision through `link_job()`. The loop does not wrap the entire batch in a transaction or catch later failures. If a subsequent shot fails validation or dispatch, the API raises an exception instead of returning the list of already-submitted jobs or the new revision. Retrying with the caller's original `expected_revision` then encounters a revision conflict, even though some jobs are already queued.

The QA38 strict regression injects a **synthetic exception on the second scheduling attempt** after allowing the first call through the actual fake-engine/SQLite-backed application path. It accepts either (a) a truly atomic rollback with no persisted jobs, or (b) a typed/sanitized failure carrying `current_revision` and `submitted_job_ids`. Existing code has neither; a failing strict test documents this contract gap, not a release-ready fix.

A separate non-strict control proves that an intentional one-shot batch can be queried through `project_render_status()` and reports two remaining missing shots. That status endpoint provides a manual recovery route today, but does not repair the failed request's missing receipt.

## Integration recommendation for the lead

Prefer **durable partial-success semantics**, not a best-effort deletion of already-dispatched work. On failure, return a sanitized machine-readable partial receipt with submitted IDs, authoritative current revision and remaining/failed shot counts. Preserve existing project CAS, order, provenance hashes, job identity and idempotent retries. Make the HTTP status and browser/mobile client behavior explicit (partial response vs typed error); never embed screenplay, shot prompts, reference paths, owner media or credentials in errors. Do not claim the whole batch was scheduled when only a prefix was accepted. Test two-device retries, interruption, restart and revision conflicts on the final integrated branch.

The default `BatchRenderRequest.max_shots=100` is intentionally bounded, and the 600-second test uses multiple batches; it is not by itself a defect. This QA concerns **unexpected mid-batch failure**, which differs from deliberate batching and from the async **master assembly** queue.

## Evidence tiers and limits

- Application-level SQLite and fake-engine worker-submission tests: exercise real persistence, revision and queue submission wiring without GPU execution.
- The injected failure is synthetic, not an observed owner-PC incident.
- No FFmpeg encode, synthetic video media, actual model inference, full 600-second owner-PC render, mobile-device playback, Windows ACL test or cloud service is exercised.
- The dedicated strict QA workflow is intentionally red until a lead-owned recovery contract is implemented. Ordinary CI skips that strict case; a green general CI does **not** mean this defect is fixed.

## Coordination / release

Review alongside master assembly [#8](https://github.com/reppiks490/new/pull/8), async master queue [#21](https://github.com/reppiks490/new/pull/21), cache/media [#23](https://github.com/reppiks490/new/pull/23), lead [#40](https://github.com/reppiks490/new/pull/40), and [#87](https://github.com/reppiks490/new/pull/87) integration ledger. The lead #40 is ahead of #8 but divergent from #21 and #23; do not merge entire divergent branches blindly. This QA modifies **no production or other-helper files** and does not authorize merges, deployments, purchases, cloud generation, owner-media transfer, ICARUS changes or automation modifications.
