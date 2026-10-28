# Character3D QA126 — source-media replacement during master assembly

**Status:** Confirmed real synthetic FFmpeg correctness/provenance defect; **not fixed**. Draft review only; do not merge automatically.

## Scope / frozen ownership

- Parent: QA124 #225, `01dedfde3dbada7ba4e8bcad92f0eb3147728c21`.
- Independent sibling of Helper 1 QA125 #226 (cache reuse/tamper). QA126 owns only `tests/test_cinematic_source_mutation_qa126.py`, `.github/workflows/cinematic-source-mutation-qa126.yml`, and this handoff.
- No changes to production service, queue, studio, media router, mobile UI, Helper 1 files, owner media, credentials, deployments, or automations.

## Reproduced behavior

`app/video/cinematic_service.py::assemble_project_master` calculates `source_hashes` and the cache `fingerprint` before invoking `_run_master_ffmpeg`. It then publishes `source_asset_hashes`, `source_digest`, and `actual_video_probe_verified=True` after FFprobe, but **does not re-read source identity before publication**. The FFmpeg command references mutable local source paths.

The deterministic test uses disposable real H.264 MP4s, not mocks of the encoder. It atomically replaces the second five-second **blue** source with a genuine five-second **green** source at the `_run_master_ffmpeg` seam, after initial SHA-256 collection and before the actual FFmpeg process opens the source. The published master contains the green segment (sampled at 7 seconds), but `source_asset_hashes[1]` attests the old blue source. This is a provenance/continuity race and can also undermine the correctness of cache identity. It does **not** prove unauthorized access, a remote exploit, or disclosure of private owner footage.

### Test-first RED evidence

- Test-only commit `3ebb2a20627bd38d0c4c52ebfc5e01081ae35b9e`.
- Workflow commit `dcd8e3ef40516485668d13e51f1e5a18fd1e9223`.
- [Dedicated real FFmpeg run #40616433490](https://github.com/reppiks490/new/actions/runs/40616433490): **completed FAILURE** on **Python 3.11 and 3.12**, each **1 passing stable-source control, 1 intended failing source-replacement case**. Both failed specifically with `SourceMediaChangedDuringAssembly: Published master consumed replacement green clip but attested the original blue clip SHA-256`. Actual FFmpeg/FFprobe were installed and used.
- Subsequent test commit `b28144eb9b6659508a830a717f69a0728b98efab` preserves **only this confirmed exception** as `pytest.mark.xfail(raises=SourceMediaChangedDuringAssembly, strict=True)`. Other failures remain red; an unexpected pass will be strict XPASS. This is not a fix.

## Proposed lead-owned correction (not implemented here)

1. Prefer an immutable per-assembly source snapshot or content-addressed read-only media objects; hash and encode the **same immutable bytes**. Avoid trusting a pathname that can be replaced after hashing. A post-encode source rehash plus fail-closed rejection is a minimum defense but does not fully eliminate transient swap-and-restore races.
2. Keep snapshots private and delete them on failure/restart; preserve bounded disk space and Windows/WSL2 filesystem semantics. Do not use a hard link alone as a guarantee against in-place edits.
3. Recheck project revision, source identities and output hashes before publishing, and make cache provenance reference the actually consumed source content.
4. Add tests for atomic rename, in-place source edits, source deletion, encode failure, and restart during snapshot/encode; verify that no stale verified master is published.
5. Integrate only after lead ownership review with #8 master, #23 cache, #40 integration, #201 audio policy, and concurrent Helper 1 #226 cache work.

## Evidence boundaries and release blockers

This is **10-second 854×480 genuine synthetic FFmpeg** media with deterministic source replacement. The race is injected at the subprocess seam; it is not a measured natural timing race under user workloads. No actual model inference, owner footage, 600-second 4K performance, Windows/WSL2 rendering, physical phone playback, or multi-API-server safety is established.

Existing blockers remain #200 multi-process startup recovery, #201 audio policy, #204 unauthorized cache denial, #213/#214 Bearer integration, #215 duplicate executor submissions, and combined integration #40. One API server per shared workspace remains required.

**Final CI ledger:** Await exact final PR HEAD and generated merge-candidate checks; no green claim until verified.
