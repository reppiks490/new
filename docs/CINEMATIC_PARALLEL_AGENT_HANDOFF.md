# Cinematic Orchestrator — parallel-agent handoff (2026-10-22)

Repository: `reppiks490/new`  
Integration target: `feat/cinematic-orchestrator-v1`  
Owner of batch/master integration: `chatgpt/cinematic-master-assembly-20261022`  
Baseline reviewed: `ba492146af3bbdab0e9cf255a9ca8b56c395a889`

## Ground truth

This is a **long-form 3D/AI filmmaking orchestration build** inside Character3D / Forma, not a repository rename. The already implemented project graph, deterministic long-prompt scene/shot compiler, continuity and references, native-vs-delivery capability planning, selected-shot queueing, privacy UI, and local engine adapters are preserved. The existing private image/video workspace is a different workstream. Do not merge other feature branches without checking for divergent modifications.

At the reviewed baseline, GitHub Actions run [39827916297](https://github.com/reppiks490/new/actions/runs/39827916297) failed: Python 3.12 had **4 failing new master-assembly tests, 597 passed, 14 skipped**; Python 3.11 was cancelled; Docker was green. The four failures were unimplemented `render_project_missing`, `project_render_status`, `MasterAssemblyNotReady` and `_run_master_ffmpeg`, not unexplained regressions.

The batch/master branch adds those pieces, typed request models, a dedicated video-master record kind, HTTP endpoints, and regression tests. Treat its CI and PR review as authoritative; **do not claim green from code presence**. Master output currently needs real FFmpeg + ffprobe quality validation and owner-hardware evaluation. Synthetic MP4 unit tests do not prove a playable cinematic release.

## Parallel ownership: one primary owner per area

1. **Chat A — Story / continuity / prompt intelligence.** Primary files: `app/video/cinematic_compiler.py`, `app/video/cinematic_models.py`, tests around story/identity/continuity, and design docs. Improve scene grammar, deterministic revision-safe shot graph edits, recurring characters, geography, props, wardrobe, lens/camera language, temporal continuity, and human-approved shot direction. Preserve deterministic output and never claim computer-vision or LLM quality without an actual implementation. Avoid changing `cinematic_service.py` or the batch/master endpoints.

2. **Chat B — Mobile cinematic editorial UI.** Primary files: `app/studio/web/cinematic-studio.js`, `cinematic-launcher.js`, `cinematic-studio.css`, and `tests/test_cinematic_ui.mjs`. Provide reliable phone editing of long prompts, scene cards, shot controls, storyboard/timeline, reference images, continuity warnings, progress badges, and accessible privacy-safe interaction. Never store raw prompts in URLs, analytics, or persistent browser storage without explicit owner approval. Avoid backend service/router edits.

3. **Chat C — Local generation / hardware and finishing.** Primary files: `app/video/adapters/`, `app/video/engine.py`, `app/video/runtime.py`, `scripts/windows/`, and rendering capability tests. Measure actual GPU/CPU, FFmpeg/ffprobe, memory, driver/tooling requirements, truthfully distinguish engine native capabilities from desired delivery FPS/resolution, and offer supported offline paths. No silent paid/cloud fallback, credential commits, model-weight commits, or invented hardware successes. Coordinate any master-assembly implementation changes with this chat's PR instead of editing its owned files in parallel.

4. **Chat D — Independent acceptance, CI and security audit.** Primary files: additive `tests/test_cinematic_*_integration.py`, `.github/workflows/ci.yml` if CI changes are proven necessary, and QA/runbook documentation. Cover exact 600-second timeline accounting, 60+ shot scenarios, restart recovery, stale revision races, auth/CORS/privacy, large prompts, failure injection, mobile browser reliability, deterministic output hashes, live-vs-mocked evidence, FFmpeg and ffprobe checks. Coordinate tests rather than rewriting the owner implementation.

5. **This chat — Batch scheduling, progress and master assembly.** Owned files: `app/video/cinematic_service.py`, `app/video/cinematic_requests.py`, `app/video/storage.py`, `app/video/router.py`, `tests/test_cinematic_master.py`, `tests/test_cinematic_master_api.py`. Implements revision-safe ordered render of missing shots; verifies every local shot is ready; composes a separate hashed master; preserves no-cloud/private data contracts; fixes CI regressions.

## Non-negotiable collaboration protocol

- Each chat creates its own uniquely named branch **from the latest audited integration branch HEAD**, commits only its primary files, and opens a PR targeting `feat/cinematic-orchestrator-v1`. No direct cross-agent branch resets, force-pushes, deletion, or unexplained cherry-picks.
- Before every edit, inspect latest branch HEAD and current open PRs; if another agent owns the same path, leave it untouched and raise a review note or use a separately named integration branch.
- All changes must preserve the existing `/api/video/generate` quick workflow, image workflows, privacy/auth middleware, and local-only inference restriction. No new provider charges or live external inference without owner approval.
- Treat **RED -> GREEN**, exact test evidence, and GitHub Actions Python 3.11/3.12 + Node 22 + Docker as mandatory. A failed/cancelled CI job cannot be described as green.
- Explicitly differentiate static/orchestration tests from real CUDA/model execution, and mock FFmpeg tests from real media playback verified with ffprobe.
- For a merge, inspect the PR diff, base freshness, CI and overlapping work. Merge safely only after ensuring unique concurrent commits are preserved.

## Acceptance milestones

1. The selected-shot workflow remains regression-green, with revision conflicts returning 409 and prompt text absent from job status metadata.
2. Batch render schedules missing/failed shots in order and does not automatically duplicate queued/running/succeeded ones.
3. Completed shots produce a private, hashed master asset with verified source provenance; incomplete assets block assembly.
4. A genuine end-to-end local FFmpeg master is probed for playable streams, duration, codec, dimensions, and frame rate; strict result matching is required for a release.
5. End-to-end 600-second multi-scene project can be edited, queued, recovered, assembled, downloaded, and privately previewed on iPhone; verify any GPU-specific steps on the actual PC.
6. Entire CI matrix is green on a single integration commit, with manual GPU/browser evidence recorded separately.

Any agent should append an evidence-based summary to its PR, not overwrite this handoff or fabricate finished capabilities.
