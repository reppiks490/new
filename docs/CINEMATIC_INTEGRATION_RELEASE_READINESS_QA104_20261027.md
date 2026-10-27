# QA104 — Character3D integration cutover readiness and ownership ledger

**Date:** 2026-10-27. **Scope:** evidence-only lead handoff for `reppiks490/new`, cinematic integration `feat/cinematic-orchestrator-v1`. **Draft / DO NOT MERGE automatically.**

**Frozen QA parent:** QA103 [#204](https://github.com/reppiks490/new/pull/204) `f993c76b047ec1b02d441740a2623c9fd36bfef4`.
This document is not a new runtime fix, test, integrated release, or owner-PC acceptance. It intentionally changes **no** production code, helper-owned paths, CI workflows, or existing tests.

## Evidence verified against current GitHub refs

- Canonical cinematic integration `feat/cinematic-orchestrator-v1`: `ba492146af3bbdab0e9cf255a9ca8b56c395a889`.
- QA103 frozen HEAD: `f993c76b047ec1b02d441740a2623c9fd36bfef4`; GitHub compare against canonical: **ahead 84 / behind 0, 96 changed paths**. The QA stack is **not** on the canonical branch merely because its draft PR checks passed.
- Lead integration [#40](https://github.com/reppiks490/new/pull/40) HEAD `05c59556d64a808dcc3a8ca96fae5e572c9e446d`; QA103 is **57 commits ahead / 0 behind** #40, but #40 is itself an unmerged draft based on `codex/filmmaking-600s-capability-proof`.
- Helper 1 private-denial hardening [#171](https://github.com/reppiks490/new/pull/171) HEAD `1ae5e4c78662509e562a05d0a512da57b987eec7` and strict-media integration trigger [#194](https://github.com/reppiks490/new/pull/194) HEAD `5ac3843d784a20ad33d27cfbc1c140b8d98ec2ac` **diverge** from QA103 at #40's `05c59556`: GitHub compare (#171 -> QA103) **ahead 57 / behind 76**; (#194 -> QA103) **ahead 57 / behind 101**. Do not treat either helper fix as already incorporated into QA103.
- Repository default branch was `claude/effort-status-tjzcfd` at inspection, **not** the canonical cinematic integration branch. Workflow `push` rules targeting `feat/cinematic-orchestrator-v1` require an actual commit on that ref to exercise them.

## Ownership and high-risk merge surfaces

| Workstream | Draft PR / exact head | Relevant ownership / collision |
|---|---|---|
| Master assembly | [#8](https://github.com/reppiks490/new/pull/8) `9e8e7ea7` | `app/video/cinematic_service.py`, `router.py`, `storage.py`, master tests |
| Durable async queue | [#21](https://github.com/reppiks490/new/pull/21) `fd4e62e4` | `app/video/cinematic_assembly_jobs.py`, `app/studio/server.py`, `router.py`, `storage.py` |
| Real-media/cache correction | [#23](https://github.com/reppiks490/new/pull/23) `c015ad18` | `cinematic_service.py`, real FFmpeg acceptance workflow/test |
| Lead integration hardening | [#40](https://github.com/reppiks490/new/pull/40) `05c59556` | `cinematic_service.py`, `cinematic_assembly_jobs.py`, media workflow, web client, provenance/timing |
| Helper 1 denial no-store | [#171](https://github.com/reppiks490/new/pull/171) `1ae5e4c7` | **Helper-owned** `app/studio/server.py` + real-media HTTP test |
| Helper 1 integration-push gate | [#194](https://github.com/reppiks490/new/pull/194) `5ac3843d` | **Helper-owned** strict private HTTP Range workflow + static trigger test |
| QA98 integration-push gate | [#199](https://github.com/reppiks490/new/pull/199) `36a503d4` | Separate 600-second fractional-cut workflow trigger; distinct from #194 |
| QA99 live-worker recovery | [#200](https://github.com/reppiks490/new/pull/200) `5b8065ae` | **QA-only strict xfail**; production recovery still unsafe across two API processes |
| QA100 source audio | [#201](https://github.com/reppiks490/new/pull/201) `5a9026aa` | **QA-only strict xfail**; source AAC dropped; preserving it is a product decision |
| QA101–103 delivery/privacy | [#202](https://github.com/reppiks490/new/pull/202) `1edb3b45`, [#203](https://github.com/reppiks490/new/pull/203) `31e107bf`, [#204](https://github.com/reppiks490/new/pull/204) `f993c76b` | Genuine synthetic 600-second faststart/seek, authenticated Range, and **strict xfail** for missing 401 no-store |

These are **draft, unmerged** PRs. Their green checks are on their **individual** commits, not a single combined cinematic integration commit. Do not merge the separate branches in numerical order without checking ancestry and cherry-pick overlap.

## Exact-head CI evidence inspected (not combined CI)

- [#8 CI 39868799240](https://github.com/reppiks490/new/actions/runs/39868799240): completed success.
- [#21 CI 39872877457](https://github.com/reppiks490/new/actions/runs/39872877457): completed success.
- [#23 CI 39870914298](https://github.com/reppiks490/new/actions/runs/39870914298) and [real-media 39870914258](https://github.com/reppiks490/new/actions/runs/39870914258): completed success.
- [#40 CI 39917307720](https://github.com/reppiks490/new/actions/runs/39917307720) and [real-media 39917307504](https://github.com/reppiks490/new/actions/runs/39917307504): completed success.
- [#171 CI 40294338134](https://github.com/reppiks490/new/actions/runs/40294338134) and [strict HTTP media 40294338039](https://github.com/reppiks490/new/actions/runs/40294338039): completed success on helper head.
- [#194 CI 40414389830](https://github.com/reppiks490/new/actions/runs/40414389830) and [strict HTTP media 40414388929](https://github.com/reppiks490/new/actions/runs/40414388929): completed success on helper head.
- [#199 CI 40439669791](https://github.com/reppiks490/new/actions/runs/40439669791) and [600s FFmpeg 40439669845](https://github.com/reppiks490/new/actions/runs/40439669845): completed success.
- [#200 CI 40445472294](https://github.com/reppiks490/new/actions/runs/40445472294): completed success **with unresolved strict xfail**.
- [#201 CI 40451125899](https://github.com/reppiks490/new/actions/runs/40451125899) and [audio 40451125885](https://github.com/reppiks490/new/actions/runs/40451125885): completed success, audio acceptance **strict xfail**, not preserved audio.
- [#202 CI 40456561539](https://github.com/reppiks490/new/actions/runs/40456561539) and [600s faststart 40456561614](https://github.com/reppiks490/new/actions/runs/40456561614): completed success.
- [#203 CI 40462697059](https://github.com/reppiks490/new/actions/runs/40462697059) and [600s authenticated Range 40462697222](https://github.com/reppiks490/new/actions/runs/40462697222): completed success. **Important false positive:** QA102's `headers.get("cache-control", "no-store")` does not prove explicit 401 no-store.
- [#204 CI 40468552460](https://github.com/reppiks490/new/actions/runs/40468552460) and [600s denial-cache 40468552305](https://github.com/reppiks490/new/actions/runs/40468552305): completed success **with strict xfail**. [Initial RED 40468374090](https://github.com/reppiks490/new/actions/runs/40468374090) confirmed 401 without `Cache-Control: no-store`; no unauthorized video bytes were shown.

**Do not equate:** mocked process/SQLite tests; genuine synthetic FFmpeg encoding/decoding; actual AI inference; owner Windows/WSL2 rendering; physical iPhone/Android streaming. The latter three remain unverified here.

## Release-blocking decisions and promotion sequence

1. **Lead freeze/ownership:** choose a single reviewable integration candidate and document exact ancestor/commit selection for #8, #21, #23, #40, QA93–103, and Helper 1's divergent #171/#194. Avoid replaying already-present commits; preserve all original branches. Do not auto-merge or force-push.
2. **Privacy gate:** integrate/review #171's narrowly owned no-store fix on a lead-owned integration branch. Remove QA103's `strict xfail` **only when the combined SHA actually passes** genuine 600-second unauthorized Range acceptance. The existing 401 rejects unauthorized requests; missing no-store is a cache-policy gap, not demonstrated footage disclosure. Keep 401/403/404 and HEAD/Range semantics explicit.
3. **Durable queue safety:** #200 proves a second API startup can mark another process's *live* assembly failed and fence out its result. Until durable lease/epoch/fencing and cross-process acceptance exist, enforce **one API server process per shared SQLite workspace**. Do not claim multi-worker safety from `BEGIN IMMEDIATE` alone.
4. **Audio policy:** #201 proves genuine synthetic source AAC is stripped by current master assembly. Lead/product must explicitly choose video-only or opt-in source-audio retention; only then implement sample-accurate audio mixing, cache versioning and real-media checks. A passing strict xfail is not audio acceptance.
5. **Combined SHA gates:** run general Python 3.11/3.12, Node, Docker, strict private Range, 600-second genuine synthetic FFmpeg (14,400 frames, all cuts, fractional timing, faststart/indexed seeks, authorized bytes and unauthorized cache headers), and queue concurrency/recovery tests. Record actual final SHA and run IDs. Verify both #194 and #199 `push` gates by **an actual authorized canonical-branch push**, not only static trigger inspection. Do not push canonical solely for this handoff.
6. **Owner acceptance after integration:** separately verify Windows/WSL2 filesystem locks, FFmpeg binary/GPU availability, local render throughput/thermals/storage, actual model inference/character continuity, source audio if selected, 4K if required, physical mobile HTTP Range/seek/reconnect over the authorized access path. Do not treat synthetic 480p acceptance as those tests.

## Boundaries and follow-up

This QA104 evidence handoff introduces **no new application fix, no newly executed FFmpeg test, and no combined-commit CI**. It is a dependency/ownership and release-readiness audit of existing GitHub evidence. Follow-up must be led by owners of #40 and Helper 1's #171/#194; do not modify their active files from this QA branch.

No merge, deployment, owner media, credentials, cloud generation, paid service, ICARUS change, or ChatGPT automation change was authorized or performed.
