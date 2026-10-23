# Cinematic master cache — verified RED and integration handoff (2026-10-23)

Scope: `reppiks490/new` Character3D / Cinematic Orchestrator only. This is a **documentation-only, disjoint QA handoff**; no production source, existing tests, owner media, secrets, deployments, or other agents' branches are changed.

## Fresh exact-head evidence

- Lead integrated draft PR #40 (`codex/filmmaking-integration-hardening`) HEAD `05c59556d64a808dcc3a8ca96fae5e572c9e446d`: general CI [39917307720](https://github.com/reppiks490/new/actions/runs/39917307720) and genuine synthetic FFmpeg acceptance [39917307504](https://github.com/reppiks490/new/actions/runs/39917307504) **passed**. These results precede the cache-history regression.
- Helper 1's independent draft PR #41 HEAD `070fa8e9dfa496cd995336ba676c64a31752c3a4`, based on PR #40, introduces `tests/test_cinematic_cache_history_helper1.py` and a dedicated two-Python-version workflow. [Run 39918800670](https://github.com/reppiks490/new/actions/runs/39918800670) **failed on Python 3.11 and 3.12** in the expected cache-reuse assertion. Both jobs successfully generated and decoded synthetic MP4 media first; on the repeat assembly, `app/video/cinematic_service.py:759` called `_run_master_ffmpeg` instead of returning the original verified master. The assertion was `Unchanged verified master was needlessly re-encoded`.
- The failing test uses a two-second 24-FPS synthetic source, verifies 48 output frames and full decode, inserts 101 unrelated `video_master` records, then repeats the identical project/revision. It is **not** actual model inference, private owner footage, or an iPhone/owner-PC validation.
- PR #41's ordinary CI jobs were still in progress at this audit snapshot. Never transfer PR #40's green status to PR #41 or a future fix.

## Root cause and repair boundary

`app/video/cinematic_service.py::assemble_project_master` currently iterates `list_video_records('video_master')` when searching for `project_id` + `source_digest`. `app/video/storage.py` delegates to `app/studio/storage.py::list_records`, which selects `ORDER BY updated DESC LIMIT 100` across **all** records of that kind. Older eligible masters are invisible after sufficient unrelated writes. This is a cache-correctness/performance defect; the current evidence does **not** demonstrate cross-project exposure.

The lead/storage owner should replace the cache candidate enumeration with a parameterized SQLite query scoped by `kind='video_master'`, exact `project_id`, and exact `source_digest`, sorted deterministically by `updated DESC, id DESC`. Do not remove the generic list limit globally or read all unrelated masters into Python. An expression index on the JSON project/digest keys can be considered after checking existing SQLite schema and query plan.

**Important candidate rule:** do not return a candidate solely because its digest matches. Preserve existing nested `probe.probe_metadata_verified is True`, file-presence, size, and on-disk SHA-256 checks. If a newer matching candidate is corrupt or missing, continue to an older matching candidate rather than treating a single `LIMIT 1` match as the only possibility. For potentially large duplicate histories, deterministic keyset pagination avoids an unbounded in-memory list while allowing verification of older candidates. The project revision and frame-accurate master identity already contribute to the source fingerprint in PR #40; retain that contract.

## Acceptance and coordination

1. Run PR #41's real-media regression **RED** against `05c59556...` (done by workflow 39918800670); then run the same test **GREEN** against the exact lead-approved source fix.
2. Add focused negative tests for a newest same-project/same-digest candidate with a missing or tampered file followed by an older valid candidate, and for an unrelated project with the same digest; never bypass probe/SHA verification.
3. Verify the combined commit with Python 3.11/3.12, Node privacy/mobile tests, Docker smoke, and real synthetic FFmpeg/ffprobe decode. Record exact commit SHAs, skipped cases, and run IDs; do not infer combined CI from ancestor success.
4. Keep PR #40 source ownership with the lead and PR #41 QA ownership with Helper 1. This handoff intentionally modifies neither path and is not a competing cache-fix proposal.
5. Preserve current constraints: no merge/deploy/cloud generation, no new paid services, no credentials/media disclosure, no changes to ChatGPT automations or ICARUS.

Other gates remain separate: actual model inference, 600-second render on the owner's PC, private mobile playback and production wiring of the master client are **unverified**.
