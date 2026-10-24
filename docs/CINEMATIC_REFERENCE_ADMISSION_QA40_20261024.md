# Cinematic reference admission QA40 — bounded engineering handoff (2026-10-24)

## Ownership and source evidence

- **Repository:** `reppiks490/new`; **frozen lead base:** PR #40 `05c59556d64a808dcc3a8ca96fae5e572c9e446d`.
- **Independent QA branch:** `chatgpt/cinematic-reference-admission-qa40-20261024`.
- **Scope:** only this new document, a new test file, and a dedicated CI workflow. No production, queue, UI, owner media, credentials, or concurrent-agent files changed.
- Existing `app/video/cinematic_reference_preflight.py::_reference_status` already rejects invalid PNG contents and >12 MiB files, but `app/video/cinematic_rendering.py::render_shot` does not call this optional preflight. `resolve_reference_ids` and `enqueue_video_job` verify the path exists; `_shot_render_provenance_digest` hashes the bytes, not their PNG decodability.
- Existing `video_asset_path` protects against path escapes/symlinks. **This QA does not claim a symlink bypass.**

## Contract and evidence levels

Three tests create an isolated SQLite-backed cinematic project, a genuine synthetic PNG, and a **held fake-engine** pool (no generation executed). The normal valid PNG is a passing control. The strict opt-in cases replace that PNG with invalid bytes or sparsely extend it beyond the already documented 12 MiB uploader boundary, confirm the independent read-only reference audit rejects it, and require `render_shot` to fail **before** a job is persisted or the project revision advances.

The strict cases are intentionally expected to fail on the frozen production base until render admission is hardened. General CI skips them so existing baseline tests remain useful; the dedicated workflow enables `CINEMATIC_REQUIRE_REFERENCE_ADMISSION_QA40=1` on Python 3.11 and 3.12. Do not interpret a green general workflow as a repaired contract.

This is real application SQLite/fake-engine scheduling with **synthetic image files**, not real video encoding, model inference, owner-PC rendering, or physical mobile playback. An invalid file reaching the queue is a local readiness/reliability gap, not proof of user-image exfiltration.

## Suggested lead-owned remediation (not implemented here)

1. Validate the selected source PNG before durable job admission, using the existing bounded byte/pixel/PNG decode semantics. Reject with a neutral, private-safe error, and do not advance project revision or submit to the worker.
2. Distinguish the selected source image from additional references: the current engine consumes `plan.source_image_id`; audit inherited references consistently with the engine's actual use and avoid gratuitous repeated decoding across hundreds of shots.
3. Avoid a race between validation, hashing and actual engine open. A prequeue audit alone is not an immutable source snapshot; recheck/lock or stage trusted immutable bytes for execution, coordinated with render-intent SHA and queue retries.
4. Preserve `video_asset_path` path/symlink protections, no raw filenames/contents in public errors, and the 600-second and offline/no-paid-provider boundaries.
5. Re-run this strict test on the integrated lead branch after a fix, plus existing reference-preflight, provenance, queue, privacy and mobile acceptance tests. No automatic merge or cloud activation.

## Dependency coordination

- **#8 / #40:** lead owns rendering/service and integration policy.
- **#21:** queued job admission/recovery must remain durable and avoid phantom revisions.
- **#23:** cached media acceptance is downstream; source image validity must not be confused with finished MP4 integrity.
- **#92:** shot *video* decode integrity is a distinct downstream source check. QA40 concerns **PNG references before generation**, not already generated shot MP4s.
- **#91:** partial-batch recovery is separate; a rejected reference must not leave a partial durable job for that shot.

Review the dedicated strict CI output for final reproducibility. Do not merge automatically.
