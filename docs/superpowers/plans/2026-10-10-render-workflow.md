# Verified 8K, 16K, and 32K Render Workflow

**Goal:** Expose real high-resolution rendering in the browser and prove the
produced file meets the requested dimensions and quality settings.

**Architecture:** Browser submits validated render settings to a persistent
scoped job API; worker uses the existing render compiler and Blender Cycles
strip/tile execution; completion requires output-file verification and a
downloadable report.

**Tech stack:** Existing `app/render/` compiler, `cycles_worker.py`, resolution
and output verification modules; FastAPI studio router/storage; Three.js UI;
pytest, Blender live tests, Playwright.

**Spec:** [BEYOND_TRIPO_SPEC.md](../../BEYOND_TRIPO_SPEC.md)

**Global constraints:** Do not accept arbitrary server paths from the browser;
render only scoped assets to scoped output files; preflight available hardware;
never label a request as completed until the output file is inspected; separate
render resolution from texture resolution and upscaling.

**Review focus:** Correct dimensions and bit depth, memory preflight, strip
seams, actual worker progress/failure, secure asset selection, and truthful
enhancement labels.

## Task 1: Scoped persistent render jobs

**Files/interfaces:** Render job schema and runner under `app/studio/`, routes
in `app/studio/router.py`, persistent state in `storage.py`, and
`tests/test_studio_render_jobs.py`.

- Write failing tests for 8K/16K/32K tier mapping, accepted settings, unsupported
  hardware, scoped asset IDs, job status persistence, timeout/failure, and
  verified completion only after output exists.
- Reuse `compile_render_job`, `run_cycles_render`, and
  `verify_render_output`; do not create a parallel resolution implementation.
  Resolve 32K support explicitly in output tiers and strip worker before adding
  a UI option. Reject if memory/hardware or current worker cannot support it.
- Implement source/output IDs rather than user-supplied file paths, with
  bounded logs and persistent progress. Add cancellation only if process
  termination is reliable and tested.
- Verify API tests and Blender live tests at small test dimensions; unit-test
  tier mapping and final dimension verification without allocating huge images.
- Commit: `feat: add verified scoped render jobs`.

## Task 2: Browser render settings and result review

**Files/interfaces:** `app/studio/web/app.js`, `index.html`, styling, browser
tests.

- Write failing tests for resolution selection, aspect ratio, format/bit depth,
  samples/denoising, hardware report, preflight warnings, job progress, actual
  dimensions, errors, and download.
- Add browser controls only for worker-supported settings; show texture
  resolution separately. Preserve camera/lighting settings for reproducible
  before/after comparisons. Keep a clear fallback if Blender is absent.
- Verify real small renders in CI where Blender exists and browser response
  using mocked bounded jobs; assert 8K/16K/32K claims against verified metadata.
- Commit: `feat: expose verified render settings and jobs`.

## Task 3: Enhancement naming and quality proof

**Files/interfaces:** enhancement capability registry, result report, render
tests and docs.

- Write failing tests that distinguish resolution, denoising, texture upscaling,
  and model-based super-resolution; absent model/provider must report unavailable.
- Expose only an operation backed by an installed, versioned model or configured
  provider; record model/version/settings and input/output hashes. Never call
  resized pixels added detail.
- Verify actual image dimensions and visual artifacts on a fixed comparison
  set with the same camera and lighting; document worker hardware/runtime.
- Commit: `feat: report verified render enhancement capabilities`.
