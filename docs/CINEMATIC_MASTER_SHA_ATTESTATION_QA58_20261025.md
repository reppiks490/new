# QA58 — completed-master SHA-256 attestation

**Draft PR #127; no automatic merge.** Frozen parent: QA57 #125 at `b1f582e1087b09f74f2733be92f5c1d836d9080d`. QA58 changes only the QA54–57-owned opt-in offline inspector and adds three QA58-only files (genuine synthetic tests, dedicated CI, this handoff). No production assembler, queue, cache, Helper 1, mobile UI, owner media, credentials, ICARUS or automations were modified.

## Source-backed gap and test-first reproduction

Lead #40 `app/video/cinematic_service.py` computes SHA-256 of assembled MP4 bytes and persists it in ready `video_master.sha256` (alongside `size_bytes`). The QA54–57 offline inspector independently checks decodability, frame count, PTS and frame durations but did not compare that stored digest with the local file.

QA58 creates genuine 48-frame/24-FPS synthetic H.264 MP4 media using libx264. FFmpeg then remuxes it with a synthetic metadata change, producing a *different file SHA-256* while preserving decodability, 48 frames, and normal timing. This is a verifier coverage defect, **not** evidence of owner footage corruption.

Test-first dedicated workflow [40185613088](https://github.com/reppiks490/new/actions/runs/40185613088) at test-only commit `cfff3e81d346ce2e0e0720010b4c84a8909a9558` produced **five intended assertion failures on each of Python 3.11 and 3.12**. Real FFmpeg provisioning and test execution succeeded; the original inspector lacked the new hash-attestation fields. The control confirms decode and timestamp correctness before asserting the absent digest gate.

## Correction and reporting semantics

The optional offline inspector now reads ready-record SHA-256 claims, checks valid 64-character lowercase hex, and compares against the actual local bytes **after successful full decode**. It checks single-link regular-file identity and pre/post hash filesystem metadata to avoid falsely attesting an obviously changing file. Duplicate records with conflicting digest claims, missing/invalid legacy digests, and unstable file metadata are **unattested**, not automatically classified as corrupted. A stable file with one valid claimed digest and different bytes is counted as a **hash mismatch**.

New aggregate-only fields: `hash_attested_masters`, `hash_unattested_masters`, `hash_mismatch_count`, and `hash_attestation_complete`. Existing `verification_complete` remains **decode-only** for backward compatibility; never mistake it for SHA, timeline, timing, source provenance or phone-playback acceptance.

The audit prints no filenames, prompts, paths, asset IDs, SHA values, credentials, FFmpeg stderr or media bytes. It does not delete, repair, upload or transcode owner media. Run only on an owner-selected **quiescent** workspace; a file changing and reverting during the scan, a detached encoder, or multi-process publication cannot be ruled out by this check. The inspector is not a sandbox for arbitrary untrusted files.

## Integration and verification boundaries

Require final exact-HEAD dedicated Python 3.11/3.12 synthetic FFmpeg CI, inherited QA54–57 workflows, and general Python/Node/Docker CI before review. Review dependencies: master #8, async #21, cache/media #23, lead #40, parent #125. Concurrent Helper 1 #124 owns in-flight source-snapshot crash/orphan QA; QA58 does not change it.

**Not established:** actual model inference, owner footage provenance, real 600-second owner-PC rendering, physical iPhone/mobile playback, source-audio lineage, durable multi-worker fencing, or safety of running while local FFmpeg workers are active. No deployment, paid service, cloud generation or merge authorization.
