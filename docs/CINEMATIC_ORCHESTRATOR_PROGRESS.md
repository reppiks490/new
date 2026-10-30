# Cinematic Orchestrator — Verification Ledger

## Resumed proof — 2026-10-23

The integration candidate now includes creative-input freshness, reference-image
SHA-256 binding, queue/master ownership checks, launcher privacy and mobile-client
reconnect regressions. It also fixes a newly reproduced preview handoff race.
See [the proof ledger](FILMMAKING_PROOF_PROGRESS_20261023.md) for exact sources,
passing checks, the nine local Blender failures, and unresolved live-generation
and master-UI gates. This is not production sign-off.

## Continuation — 2026-10-23, ten-minute maximum and proof requirement

The owner now requires a maximum film length of 600 seconds and real evidence
before a filmmaking link is called fully capable. The duration policy covers
new/updated targets, edited shot totals, compilation, native render plans,
batch scheduling, synchronous assembly and async assembly admission. Legacy
documents remain readable. The frontend rejects invalid selections rather than
silently replacing them. See [the acceptance record](FILMMAKING_ACCEPTANCE_600S.md)
for exact native-vs-delivery limits, observed unavailable GPU/model runtime,
required live proof, and the pending backend choice. No superior-to-WAN or
error-free arbitrary-prompt claim is accepted from the existing tests.

---

Branch: `feat/cinematic-orchestrator-v1`
Spec: `docs/superpowers/specs/2026-10-22-cinematic-orchestrator-design.md`
Plan: `docs/superpowers/plans/2026-10-22-cinematic-orchestrator-v1.md`

This file is the durable implementation/verification ledger for the long-form filmmaking build. It exists so the state of the project does not depend on chat history.

## Quality policy

- No completion claim without fresh executable evidence.
- New behavior is developed RED -> GREEN.
- Delivery targets (for example 2160p/120 FPS) are never described as native generation capability unless the selected engine actually supports them.
- No paid API, CUDA runtime, external LLM, or FFmpeg dependency is required for orchestration unit tests.
- Existing quick image-to-video behavior must remain backward compatible.
- Final sign-off requires the complete GitHub CI matrix: Python 3.11, Python 3.12, Node browser tests, Docker build and `/health` smoke test.

## Task 1 — Cinematic domain + storage

### RED evidence

Commit: `a89e169fcd3b252e977f4974bb498f990401d4d0`
GitHub Actions run: `39822411924`
Python 3.12 job: `119976830434`

Observed result:

- `6 failed`
- `558 passed`
- `14 skipped`

Every failure was intentional and new:

- 5 failures: `ModuleNotFoundError: No module named 'app.video.cinematic_models'`
- 1 failure: `ValueError: Invalid video record kind` for `video_project`

No pre-existing test failed in the RED run.

### Implementation

- `app/video/cinematic_models.py`
- `app/video/storage.py` accepts `video_project`
- Blank `master_prompt` rejected at the model boundary.

Commits include:

- `515acfedaba47adfe2394ebe85b9e985ac4bf8c8` — cinematic domain models
- `a30cc56e818e7e019a0936960c9a36dd9b2faa00` — cinematic project storage kind
- `31e3f3b8a15dc1d5ee723bc20e4534fa66878060` — blank prompt hardening

### Full-CI status

Run `39822773650` was created for the Task 1 GREEN state. GitHub runners remained externally queued during implementation. This is a runner-availability condition, not accepted as proof of success. Final sign-off still requires a completed fresh full CI run.

## Task 2 — Deterministic long-prompt compiler

### RED definition

Test commit: `404b91c99f1063e0c8e654ebed71d000e29a5f97`

The tests pin:

- four explicit scene-marker syntaxes
- paragraph/sentence fallback decomposition
- automatic scene chunks <= 2,000 characters
- deterministic scene/shot IDs
- exact 600-second timeline budgeting
- exactly 60 shots for a 600-second target at a 10-second cap
- no shot exceeding engine duration caps
- blank prompt rejection
- iterative 100,000-character prompt compilation

### Implementation

Compiler commit: `3f671463047507cc033c6dba216925a374cf01ce`

Module: `app/video/cinematic_compiler.py`

Properties:

- zero-network / zero-LLM deterministic compiler
- explicit scene boundaries preserved
- automatic long-prose decomposition is iterative, not recursive
- stable SHA-256-derived opaque IDs
- duration arithmetic uses `Decimal` before conversion to stored floats
- global shot count is bounded by selected engine duration capability
- shot prompts use scene-local source material rather than blindly injecting the entire master prompt

### Local hermetic GREEN evidence

The exact committed model/compiler logic and the committed compiler test cases were copied into an isolated local Python harness and executed with pytest.

Result:

- `8 passed in 0.11s`
- Includes the 100,000-character stress case.
- Includes the exact 600-second / 60-shot case.
- Includes strict max-duration validation.

A separate unrelated spreadsheet-runtime warmup warning emitted by the host environment after pytest and did not affect the test process (`pytest` exit code 0).

## Runner-backlog execution ruling

GitHub Actions became queued for an extended period after the clean RED evidence was captured. To avoid halting implementation while preserving rigor:

1. Pure orchestration modules are allowed to advance using hermetic local RED/GREEN execution.
2. Every commit remains on the isolated feature branch.
3. Full GitHub CI is still mandatory before the branch can be called complete or merge-ready.
4. If final CI exposes any discrepancy, the discrepancy overrides local evidence and must be fixed before sign-off.

## Remaining implementation gates

- Task 3: atomic project persistence, optimistic revisions, continuity inheritance, reference resolution
- Task 4: capability-aware immutable render plans
- Task 5: cinematic API
- Task 6: shot-level queue integration
- Task 7: mobile Project Mode + privacy/browser tests
- Task 8: exact 600-second end-to-end acceptance fixture + runbook/setup docs
- final line-by-line spec audit
- final privacy/security review
- final full GitHub CI matrix


---

## 2026-10-22 — Master-assembly and parallel-agent continuation

The earlier "Remaining implementation gates" section above is a historical snapshot, not the latest implementation state. The latest continuation resides on \`chatgpt/cinematic-master-assembly-20261022\`, tracked in [PR #8](https://github.com/reppiks490/new/pull/8). Other agents own PRs #9–#12; see \`docs/CINEMATIC_PARALLEL_AGENT_HANDOFF.md\` for file ownership and merge discipline.

### Prior clean baseline

At \`c878afb549c8bda8ac340a7dfba878759473e236\`, **both** runs [39860203471](https://github.com/reppiks490/new/actions/runs/39860203471) and [39860196877](https://github.com/reppiks490/new/actions/runs/39860196877) passed Python 3.11 / 3.12, Node privacy tests, and Docker. This does **not** confer green status on later commits; review the CI of PR #8's **current** head.

### Added capabilities and hardening

- Project-wide \`render-missing\` batch scheduling (oldest timeline shots first) with optimistic project-revision updates and no duplicate in-progress jobs.
- Missing/corrupt successful-job output MP4s are treated as eligible for retry; a metadata success flag alone is insufficient.
- \`render-status\` distinguishes missing/failed/active/success and does not expose raw cinematic prompts.
- FFmpeg master creation requires every source job to succeed and its local file to exist.
- Only \`ffmpeg\` and \`ffmpeg.exe\` may be named by the HTTP request, to avoid running arbitrary client-chosen binaries.
- Master cache identity incorporates the actual source-media SHA-256 hashes, shot ordering and duration, project revision, aspect ratio, and delivery settings. Master record stores an output SHA-256 checksum and source hashes.
- FFprobe checks video codec H.264, dimensions, delivery FPS, frame count, and total duration. No record may be marked complete when probe validation fails; partial output is deleted.
- Concurrent project edits during long master assembly invalidate the result before persistence.
- Master rendering explicitly uses \`-r <delivery_fps> -fps_mode cfr\` at the output stage.

### Real local synthetic FFmpeg experiment

On the task execution host, two generated **one-second synthetic** 160×90 MPEG-4 input clips (native 12 FPS and 30 FPS) were assembled to 854×480/24 FPS H.264 output.

- Original filter chain **without** explicit output CFR: ffprobe reported **48 frames, 1.958333 seconds, and an incorrect average FPS**.
- With output \`-r 24 -fps_mode cfr\`: ffprobe reported **48 frames, exactly 2.000000 seconds, and avg_frame_rate 24/1**.
- Added \`tests/test_cinematic_ffmpeg_live.py\` to exercise real FFmpeg output when both FFmpeg and FFprobe are present on the CI runner, then **decode the full synthetic master** and test hash-based reuse.
- All mock-based unit tests remain valuable but do not establish actual human-observed movie quality or live GPU image-to-video generation.

### Still unresolved before a production release

- Fresh full CI on PR #8's most recent commit, including the real FFmpeg test wherever supported.
- Real user-PC environment check for FFmpeg/FFprobe and actual video model availability; no assertion of GPU compatibility.
- Private iPhone-to-PC authenticated previews of real generated video, not just test clips.
- Large timeline performance / Windows command-line length / multi-stage concatenation stress under actual hardware.
- A nonblocking background **server-side queue** for long FFmpeg assembly: the existing synchronous \`POST /assemble\` may exceed phone/browser timeout for long 4K masters.
- Audio/soundtrack mixing, transitions, scene-fade grammar, image visual consistency, and manual visual QA of start/middle/end and scene boundaries.
- Independent PR review and orderly merge of the four helper workstreams; no destructive branch reset or forced merge.

Definition of done is tested, decodable, private, correctly timed media with explicit engine/hardware evidence, not merely a green mocked backend.
