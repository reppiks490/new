# QA80 — MP4 movie-header opaque-suffix privacy integrity

**Status:** isolated draft; do not merge. Parent QA79 #169 at `7e59bff4c9ba3312fd8fe03bab05639c9626e159`; its exact-head workflow outcomes were **21 successes / 6 cancellations** (27 total), not all green.

## Reproduced test-first defect

Test-only commit `a92b1d28384e3695bfd7f6f5cb3830f61153d19b`, [QA80 CI 40293859900](https://github.com/reppiks490/new/actions/runs/40293859900), completed **FAILURE** on Python **3.11 and 3.12**. Both job logs independently showed **1 failed / 1 passed**, and the failure was the intended strict-audit assertion: the opaque-suffix media returned **0** instead of required **1**, not a setup failure.

A disposable synthetic FFmpeg H.264 MP4 contains a private test canary appended **inside** the permitted `moov/mvhd` movie header. Both the enclosing `moov` and `mvhd` declared lengths were updated. FFprobe still reported H.264, 48 frames / 24 FPS / 2 seconds without the canary; full video decode, legacy decode-only audit, and temporary SQLite persisted SHA-256 passed. Strict offline attestation incorrectly passed. No owner media or remote exploit is implied.

## Narrow proposed correction

Commit `d64b09f225937bf3e8bb5417e46f664270fb2ed2` checks that `mvhd` FullBox has zero flags, a supported version, and **exactly** its ISO-BMFF version-dependent length (100 bytes payload for v0 or 112 for v1, plus the box header). It reads only four nonprivate version/flags bytes and does not log payloads. The correction is confined to the opt-in read-only completed-master inspector; legacy decode-only behavior is unchanged.

The regression test is genuine synthetic FFmpeg/FFprobe H.264 plus temporary SQLite, not mock-only. Require the dedicated Python 3.11/3.12 final-head workflow, general CI and inherited compatibility checks at the final commit before any green claim. Cancelled/queued checks are not successes.

## Ownership and limitations

- Dependencies: #8 master assembly, #21 async queue, #23 cache/media acceptance, #40 integration, #169 QA79 parent.
- Helper 1 #168 owns private-media snapshot failure/recovery and Docker/runtime tests. No production worker, queue, router, cache, mobile UI or Helper 1 files were changed.
- This is a narrow structural privacy attestation, **not comprehensive MP4 sanitization**; alternative muxers, arbitrary nested payloads, encoded pixels and source provenance remain separate.
- Actual model inference, owner footage, complete 600-second owner-PC render, physical mobile playback, Windows ACL/reparse behavior and multi-process durable fencing remain unverified.
- No merges, deployments, cloud generation, purchases, credentials, force pushes, ICARUS or ChatGPT automation changes.
