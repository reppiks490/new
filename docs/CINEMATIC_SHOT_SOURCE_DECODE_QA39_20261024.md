# QA39 — shot-source decode integrity before master assembly (2026-10-24)

## Scope and frozen ownership

- Dedicated additive QA-only branch from lead #40 `05c59556d64a808dcc3a8ca96fae5e572c9e446d`.
- No edits to `app/video/cinematic_service.py`, `app/video/jobs.py`, queue, router, UI, concurrent-helper files or existing tests.
- Draft, not a production fix. No merges, deployments, cloud generation, owner media, secrets or model inference.

## Concrete application defect and reproduction

`app/video/jobs.py::_valid_mp4` checks only file size >=12 and `ftyp` within its first 64 bytes. `app/video/cinematic_service.py::_job_has_local_render` uses that predicate to treat a succeeded shot as locally available; `project_render_status` then reports `ready_for_assembly=True` when all shot records pass. `assemble_project_master` uses the same predicate before invoking FFmpeg.

The new regression creates a **genuine synthetic 24-fps H.264 MP4** with local FFmpeg, confirms FFprobe and full FFmpeg decode succeed, persists a real SQLite cinematic project/job link, then truncates the media to its first 64 bytes. The remaining `ftyp` header passes `_valid_mp4`, but real FFprobe and full FFmpeg decoding reject it. The strict test expects the application **not** to advertise this source as ready. Current lead code is expected to fail that final assertion.

This is a source-shot acceptance gap, distinct from #50/#54 (master decode/cache), #90 (underlength but decodable shot), and #49 (queued master output identity). The control test verifies an actually decodable synthetic source is accepted and that the status response does not echo the private synthetic prompt.

## Suggested lead integration contract

1. Define the readiness tiers explicitly: signature-only *exists*, probed *structurally valid*, and full-decoded *verified*. Do not call signature-only `ready_for_assembly` without a documented policy.
2. For authoritative queue admission, verify source media with bounded FFprobe and a bounded full decode (or a justified equivalent), enforcing exactly the expected video stream and safe resource limits. Reject corrupt/truncated sources with neutral diagnostics; do not return paths, prompts or subprocess stderr to mobile.
3. Cache verified results only against authenticated file identity (content SHA-256 plus validation version), invalidate on source mutation, and recheck identity before encode/publication. Avoid repeatedly decoding every shot on every status poll.
4. Preserve the existing idempotent shot re-render and stale-revision behavior; coordinate with #21 queue and #23 cache/media acceptance, and the lead #40. Do not blindly merge divergent histories.
5. Exercise synthetic corrupt/valid clips on Python 3.11 and 3.12; separately validate long-form resource budgets and owner-PC/physical-phone playback.

## Evidence boundaries

This QA uses actual SQLite-backed project/job records and **genuine synthetic FFmpeg encoding, FFprobe, and full decoding**. It does not exercise actual model inference, owner footage, a 600-second owner-PC render, physical mobile playback or Windows ACLs.

The strict test is opt-in via `CINEMATIC_REQUIRE_SHOT_SOURCE_DECODE_QA39=1` and expected RED until production admission is fixed. Ordinary CI skips that assertion; green general CI does **not** prove the source-integrity defect is fixed. Check exact final-head workflow conclusions before any integration.
