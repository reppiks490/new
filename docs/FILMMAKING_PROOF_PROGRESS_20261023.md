# Resumed filmmaking proof — 2026-10-23

The owner asked to continue proving the image-to-film build after the saved
checkpoint. This integration candidate starts at
`e50efbe62dfa7fb21ffa1074d109c35868aa2c92`, which preserves the 600-second film
policy. It is isolated from the deployed 3D studio and the original proposals.

## Changes and reproduced failures

- Queue publication now requires the returned master to belong to the queued
  project/revision and match its persisted `video_master` record. All eight
  adversarial cases from PR #34 failed before the fix and passed afterward.
  The mock success fixture now writes an actual matching database record.
- Integrated PR #29/#37 freshness/provenance changes from
  `ca19298d925d388abc30ed0eb1dbf3720d7dd9d8`: creative edits detach old render
  links, and new jobs record a versioned digest of creative inputs, native
  settings and actual reference PNG bytes. Of the 32 imported regression cases,
  24 failed before integration; all pass afterward. The merge conflict was
  resolved by retaining both the duration check and stale-link invalidation.
- Integrated launcher privacy/lifecycle work from PR #38, preserving the
  ten-minute controls. Late startup/poll/media responses cannot reopen a hidden
  or exited workspace. Preview URLs are revoked on hide/exit.
- Independent review reproduced a preview handoff failure: a newly completed
  shot was skipped while the previous preview downloaded. The new regression
  failed before correction. Different jobs now supersede/abort pending previews;
  duplicate requests for the same pending job remain deduplicated. Four further
  red-to-green cases restrict authenticated preview fetches to exact local MP4
  asset paths; redirects are rejected.
- Integrated reconnect/backoff code and tests from PR #28/#36 snapshot
  `bc84ab885f098ce03f80d0747dab2176128c7e4a`. Seven cases failed before integration
  and pass afterward. The older stable-pagination fixture used the same job ID
  twice; it now uses distinct IDs rather than weakening duplicate detection.
- A subsequent real-media timing experiment reproduced fractional-cut drift:
  four 2.525-second shots at 24 FPS produced 244 frames, while cumulative time
  requires 242. Assembly now uses the existing editorial timeline's cumulative
  frame allocations, frame-count trimming and padding. Probe validation requires
  that exact count and rejects delivery duration beyond 600.001 seconds. A new
  cache version prevents reuse of older masters with accumulated drift. Stored
  master metadata includes the editorial timeline identity and frame count.

## Executed evidence

- Video/cinematic Python suites: **335 passed**, warnings treated as errors,
  after the cumulative-frame correction and four added precision regressions.
- Node browser/privacy suites: **81 passed** after the preview corrections.
- Full local Python suite before the timing follow-up: **823 passed, 9 failed**
  in 196.92 seconds. All nine
  failures are in the existing `tests/test_blender_live.py` suite, on this
  environment's Blender 4.3.2 build. Denoising fails with no OpenImageDenoise
  support; the system executable also returns zero after a Python script error.
  Failed cases, retained without suppression:
  - `test_real_cycles_render_is_verified[png]`
  - `test_real_cycles_render_is_verified[exr]`
  - `test_render_is_lit_not_black_or_blown_out`
  - `test_production_worker_exports_only_the_asset`
  - `test_blender_shim_script_errors_exit_nonzero`
  - `test_bake_measures_reach_hits_the_surface_and_flags_empty_udim_tiles`
  - `test_bake_pinned_to_the_old_2cm_reach_is_rejected_by_its_measured_miss_rate`
  - `test_render_applies_displacement_with_adaptive_subdivision`
  - `test_render_scatters_see_through_3d_trees_and_leaves_no_stray_files`
- Imported PR #32's real authenticated HTTP queue -> FFmpeg -> private-download
  test from `e69d4cf7a0307704fa41c980aad0be2237742bf3`. It creates two synthetic
  clips at different source frame rates, produces a ten-second H.264 master,
  verifies 854x480, 24 FPS and 240 frames, fully decodes it, checks downloaded
  SHA-256, denies missing/query-string bearer credentials, reuses the verified
  cache, then invalidates the cache when source MP4 bytes change.
- Independent code review found the preview handoff issue, then verified its
  correction and all 18 launcher regressions. No additional important backend
  regression was identified. These are implementation checks, not creative
  quality, native inference or actual iPhone evidence.

The complete local run predates the cumulative-frame follow-up, which was then
verified with the full video/cinematic suite. The dedicated real-media workflow
now requires and runs the private queue and fractional-frame tests alongside the
existing media test. Final GitHub Python 3.11/3.12, Docker and real-media results
must be recorded separately; earlier proposal CI does not verify this change.

## Gates still open

- No GPU, CUDA runtime or model weights are installed here. Rechecked Runway:
  authenticated, Free workspace, `availableVideoModels: []`. Rechecked Hugging
  Face jobs: tool returned `UNAVAILABLE`. No paid generation or GPU job ran.
- The owner has been asked which live backend can be used: their NVIDIA worker,
  activated Runway video access, or a cloud GPU with a spending limit. Live
  inference depends on that information/access. A connected chat tool is not
  automatically an authenticated provider adapter for a deployed application.
- The master client is **not wired into the production frontend**. Its tested
  reconnect primitive is not a delivered master-assembly UI flow. Finish that
  integration and real phone lifecycle tests before release.
- Legacy clips lacking input digests remain readable and are explicitly counted
  as unverified; do not approve them as source-fresh merely from assembly-ready
  status. Input hashing does not remove the file-mutation race between hashing
  and model consumption, nor prove that a model obeyed a reference.
- The live URL remains the separately deployed 3D studio with mobile import fix
  `4bdd647fe979c0965d083d1029e4bd63ce8b7436`. This candidate has not replaced it.
- No generated ten-minute film, WAN superiority, flawless anatomy, unrestricted
  prompt compliance, native 4K/120 FPS or actual iPhone pass has been proven.

Next: obtain a usable rendering backend, submit a real source image and prompt
through the delivered UI/API, retain actual output and execution identity,
verify the MP4 and watch it for reference fidelity and action compliance. Keep
native generation separate from delivery rescaling/frame conversion.
