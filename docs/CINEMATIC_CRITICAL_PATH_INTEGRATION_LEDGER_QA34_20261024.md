# Character3D cinematic critical-path integration ledger — QA34 (2026-10-24)

**Status: evidence-based coordination only; not a production fix or release approval.**
**Frozen review base:** lead integration PR [#40](https://github.com/reppiks490/new/pull/40) at `05c59556d64a808dcc3a8ca96fae5e572c9e446d`.
**Scope:** Character3D / 3D filmmaking on `feat/cinematic-orchestrator-v1`. This document does not change source, workflows, media, credentials, owner hardware, automations or any ICARUS repository.

## 1. Why this handoff is needed now

There are many open, disjoint QA drafts with **green general CI but deliberately red focused production regressions**. The highest-value next engineering work is **reviewed lead-owned integration and retesting**, not another independent test of the same defect. Green baseline CI does not erase a failing strict regression; conversely a red strict QA draft is not a blanket failure of every application test.

The most important ancestry finding is that [#40](https://github.com/reppiks490/new/pull/40) is **8 commits ahead / 0 behind** [#8](https://github.com/reppiks490/new/pull/8), but GitHub compare reports it **diverged** from [#21](https://github.com/reppiks490/new/pull/21) (**8 ahead / 15 behind**, merge base `9e8e7ea7`) and from [#23](https://github.com/reppiks490/new/pull/23) (**8 ahead / 2 behind**, same merge base). Nevertheless #40 contains a revised `app/video/cinematic_assembly_jobs.py` and a nested `probe.probe_metadata_verified` cache check. Therefore **do not blindly merge the entire #21 or #23 branches into #40** or claim they are wholly absent/present based on commit ancestry alone. Compare the exact file-level behavior, preserve unique commits and helper ownership, and rerun targeted tests on the chosen integration head.

## 2. Exact-head CI ledger (read from GitHub Actions)

| PR | Frozen head | General CI | Focused workflow | Interpretation |
| --- | --- | --- | --- | --- |
| [#8](https://github.com/reppiks490/new/pull/8) master | `9e8e7ea7` | [39868799240](https://github.com/reppiks490/new/actions/runs/39868799240) success | — | Initial assembly baseline, not release acceptance |
| [#21](https://github.com/reppiks490/new/pull/21) async | `fd4e62e4` | [39872877457](https://github.com/reppiks490/new/actions/runs/39872877457) success | — | Durable queue baseline, later lead divergence |
| [#23](https://github.com/reppiks490/new/pull/23) cache/media | `c015ad18` | [39870914298](https://github.com/reppiks490/new/actions/runs/39870914298) success | [39870914258](https://github.com/reppiks490/new/actions/runs/39870914258) success | Synthetic real-media acceptance |
| [#40](https://github.com/reppiks490/new/pull/40) lead | `05c59556` | [39917307720](https://github.com/reppiks490/new/actions/runs/39917307720) success | [39917307504](https://github.com/reppiks490/new/actions/runs/39917307504) success | Current frozen integration candidate, not complete release |
| [#79](https://github.com/reppiks490/new/pull/79) E2BIG | `437d1ce6` | [40054892664](https://github.com/reppiks490/new/actions/runs/40054892664) success | [40054892737](https://github.com/reppiks490/new/actions/runs/40054892737) **failure** | Intended strict process-launch regression |
| [#80](https://github.com/reppiks490/new/pull/80) script transport | `38b025f2` | [40059318774](https://github.com/reppiks490/new/actions/runs/40059318774) success | [40059318796](https://github.com/reppiks490/new/actions/runs/40059318796) success | Isolated mitigation, not wired to production |
| [#81](https://github.com/reppiks490/new/pull/81) many-input memory | `e22796a4` | [40063157355](https://github.com/reppiks490/new/actions/runs/40063157355) success | [40063157435](https://github.com/reppiks490/new/actions/runs/40063157435) **failure** | Intended strict thread-bound regression |
| [#82](https://github.com/reppiks490/new/pull/82) geometry | `95fea20d` | [40067104316](https://github.com/reppiks490/new/actions/runs/40067104316) success | [40067104288](https://github.com/reppiks490/new/actions/runs/40067104288) **failure** | Create/update admission remains missing |
| [#83](https://github.com/reppiks490/new/pull/83) chapters | `2e9fee3d` | [40071058723](https://github.com/reppiks490/new/actions/runs/40071058723) success | [40071058787](https://github.com/reppiks490/new/actions/runs/40071058787) **failure** | Synthetic source chapters inherited |
| [#84](https://github.com/reppiks490/new/pull/84) stream inventory | `c7dcf0ca` | [40075013172](https://github.com/reppiks490/new/actions/runs/40075013172) success | [40075013179](https://github.com/reppiks490/new/actions/runs/40075013179) success | Optional acceptance gap, not demonstrated production leak |
| [#85](https://github.com/reppiks490/new/pull/85) HDR/SDR | `d0e2fffe` | [40078853975](https://github.com/reppiks490/new/actions/runs/40078853975) success | [40078854013](https://github.com/reppiks490/new/actions/runs/40078854013) **failure** | Synthetic PQ metadata survives generic master |
| [#86](https://github.com/reppiks490/new/pull/86) private file modes | `965e1224` | [40083043555](https://github.com/reppiks490/new/actions/runs/40083043555) success | [40083043561](https://github.com/reppiks490/new/actions/runs/40083043561) **failure** | Linux umask 022 permits group/other bits |

The focused red runs are **not fixes**. No owner-PC ACL, real model inference, 600-second full owner-hardware render, or physical mobile playback is established by these checks. Exact run IDs and head SHAs should be refreshed before any later integration or merge.

## 3. Proposed non-destructive lead integration order

1. **Reconcile lineage and ownership first.** Choose the lead's active integration branch, inspect #8/#21/#23 and #40 file-level differences, and reconcile only missing functionality. #21 owns async queue behavior; #23 owns cache/media candidate; #28/#36 own mobile client; #40 owns integration/service; Helper 1 privacy QA (#73–#75) and QA drafts (#79–#86) remain isolated. No force push, branch reset, automatic merge, or overwrite of another contributor's active files.
2. **Protect private local artifacts before broader media testing.** Use [#86](https://github.com/reppiks490/new/pull/86) as a test-first contract for private workspace/SQLite/WAL/SHM, FFmpeg child outputs, existing-file migration and Windows ACL review. Preserve the actual project DB and existing media. Use [#73](https://github.com/reppiks490/new/pull/73) and [#83](https://github.com/reppiks490/new/pull/83) for both format metadata and chapter suppression; review `-map_metadata -1` **and** `-map_chapters -1`. Revalidate cached masters after a privacy policy/version change.
3. **Reject impossible work before durable queue admission.** Review [#82](https://github.com/reppiks490/new/pull/82) geometry admission on both project create and update, plus pre-assembly validation. Pick explicit local-hardware-safe pixel/dimension limits rather than assuming an arbitrary policy is universally correct. Preserve existing project records on rejection.
4. **Make long-form FFmpeg executable under bounded local resources.** [#79](https://github.com/reppiks490/new/pull/79) reproduces Linux single-argument `E2BIG`; [#80](https://github.com/reppiks490/new/pull/80) offers an isolated private `-filter_complex_script` helper; [#81](https://github.com/reppiks490/new/pull/81) demonstrates decoder/filter thread memory pressure. Integrate only after reviewing 0600 temporary-file lifecycle, abrupt crash cleanup, per-input decoder threads, filter threads, worker serialization, disk/RAM admission and failed-job cleanup. A 700-input synthetic low-resolution encode is **not** proof of 700 distinct owner clips or owner-PC memory capacity.
5. **Close media acceptance without hiding quality failures.** Review [#84](https://github.com/reppiks490/new/pull/84) for complete stream inventory; [#85](https://github.com/reppiks490/new/pull/85) for explicit SDR-vs-HDR policy. Never merely relabel PQ pixel values as BT.709; choose true tone mapping or a separate supported HDR delivery contract. Combine with the existing integrity, full decode, faststart, keyframe/seek, square-pixel/rotation and audio/timestamp QA branches as appropriate. Silent masters and optional audio need separate acceptance contracts.
6. **Verify queue-to-mobile end-to-end after production fixes.** Preserve revision/project/master identity, persisted SHA, terminal-state idempotency, cancellation and restart behavior, authenticated private byte-range/HEAD, mobile reconnect and no-store protections. Check the older async/cached-output race QA, including source mutation, artifact swap and stale edits. Require actual final-commit CI on the **combined integration head**, not just green tests on independent branches.
7. **Only then run owner-local acceptance.** Confirm full 600-second rendering, real model inference, actual hardware resource use and real phone playback separately, with explicit owner permission and no cloud generation, payment, broker action or media upload.

## 4. Evidence tiers and signoff

- **Mocked application tests:** validate API/state/control flow; not FFmpeg, inference or phone proof.
- **Real synthetic FFmpeg tests:** establish actual codec, container, timing, decode or kernel/process behavior for generated test fixtures only.
- **Real model inference:** requires installed model weights and a measured local inference run; not established by mock jobs or FFmpeg-only work.
- **Owner-PC verification:** actual OS/ACL, memory, disk, full-duration and crash-recovery evidence on the owner's machine; not established by CI runners.
- **Physical mobile verification:** authenticated streaming, Range/HEAD, seek/reconnect and playback on a real phone/network; not established by offline MP4 preflight.

**Release condition:** strict previously-red regressions must become green against the final integrated production implementation; privacy/cache migration policy must be explicit; general CI, focused FFmpeg, Node/browser, Docker and queue/mobile tests must all pass on the exact final commit. Otherwise keep drafts unmerged and mark blocked.

## 5. QA34 disposition

This is a **new coordination document only** on a disjoint branch, not a patch to production and not a claim of resolved blockers. No redundant new strict regression was added because the above defects already have dedicated reproductions and CI. The next implementation owner should prioritize reviewed integration over generating more overlapping QA branches. No automated merge, deployment, owner-media transfer, paid service, cloud inference, automation change or ICARUS modification is authorized by this ledger.
