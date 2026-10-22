# Cinematic Orchestrator — Independent Timeline & Release QA

**Owner:** Helper Bot 4 / independent QA  
**Scope:** additive acceptance tests, release evidence, security checks.  
**Production runtime modifications:** none in this workstream.

## Evidence boundaries

- Deterministic shot/scene graphs and frame accounting do not generate or validate visual frames. They prove temporal accounting and deterministic metadata only.
- Synthetic MP4 headers used by isolated tests are not playable-media evidence.
- Green Python/Node/Docker CI is necessary but not sufficient for a film release.
- No actual GPU inference, paid API, or external model use is authorized by these tests.

## Test oracle

Run on the repository checkout:

    python -m pytest -q -W error tests/test_cinematic_timeline_integration.py

The single test file has no effect on production request paths and contains an independent, privacy-minimized frame manifest oracle. It checks:

1. Half-open shot intervals with no gaps/overlaps and consistent scene spans.
2. Decimal cumulative frame rounding to avoid long-film rounding drift.
3. 24 FPS / 600 seconds = **14,400 planned frames**; a 9-second maximum shot duration requires **67 ordered shots**.
4. Explicit mismatch reports if shot runtime differs from the delivery target.
5. Rejection of unrepresentably short, nonfinite or duplicated shot inputs.
6. No private prompts, screenplay text, or continuity notes in frame-manifest output.
7. Deterministic digest changes when project revision or shot order changes.
8. Persistence/read-after-write recovery and optimistic-revision stale-write rejection.
9. Stable compilation of a 100,000-character master prompt.
10. Hermetic testing without GPU models, video jobs, FFmpeg or paid providers.

### Editorial semantics

- Intervals are half-open: [in_frame, out_frame_exclusive).
- Timecodes are integer-FPS, non-drop labels, not SMPTE drop-frame timecodes.
- The manifest is a test oracle and is not yet a production EDL or rendering artifact.
- Timeline SHA-256 is an edit-graph identity, not a content hash of video files.
- A timeline can be off target; inspect target_alignment_delta_frames.

## Additional operational recovery tests

Run all independent cinematic QA suites from a repository checkout:

    python -m pytest -q -W error tests/test_cinematic_timeline_integration.py tests/test_cinematic_recovery_integration.py tests/test_cinematic_longform_batch_integration.py

Recovery tests use the existing fake local engine and capture-only GPU job pool. They make no real model or FFmpeg calls. They verify:

- A process restart marks active/queued jobs interrupted/failed, while completed jobs remain linked to their original local assets.
- Bounded retries pick failed and missing shots in timeline order; active jobs are never duplicated, and no-op retries do not advance the project revision.
- Stale project revisions reject queued work without creating extra jobs or mutating stored state.
- A foreign-project job ID linked into the wrong project is not trusted, even when it claims success.
- Failed FFmpeg invocations and outputs with invalid MP4 signatures remove partial output and do not create a master record.
- A 600-second, 60-shot, three-scene film can be queued in bounded 13-shot batches without skipping/reordering shots; after a restart, bounded seven-shot retry preserves the full shot graph.

**Limits:** this does not simulate an actual process crash during a SQLite transaction, overlapping workers with independent OS processes, GPU/CPU exhaustion, external decoder failure, or real FFmpeg/ffprobe. It does not prove source immutability or cross-revision content freshness. Those remain integration/release gates rather than silently counted as passing QA.

## Additional evidence required before calling a cinematic master verified

Record commit SHA, CI run IDs, actual hardware/software versions, asset count and hashes, render command, exit status and ffprobe metadata. On the real generated master file (not synthetic bytes), execute:

    ffprobe -v error -show_streams -show_format -of json /path/to/master.mp4

Verify all of the following:

- FFmpeg exited 0, file exists, is substantial and a decoder can actually read it.
- ffprobe reports video stream, actual codec, width, height, FPS rational frame rate and duration.
- Film plays at beginning, several scene boundaries and end without blank/corrupt frames.
- Actual duration and frame count meet a documented tolerance; conversion from native generation is honestly labeled.
- Input shots belong to the right project/scene/shot and are ordered; inspect revision and source provenance.
- Test stale concurrent edits, interrupted/restarted jobs, partial output and missing source assets.
- Verify prompts and keys never appear in URLs, logs, filenames, telemetry or unauthenticated endpoints.
- Test the full workflow on the target phone and PC, including mobile accessibility and privacy controls.

## CI sign-off

Require the same commit SHA to pass Python 3.11, Python 3.12, Node 22 browser tests and Docker boot/health smoke test. A cancelled job is not a pass. Report the exact regressions. Do not mute warnings, skip acceptance tests or weaken assertions for artificial green.

## Merge discipline

Merge only by reviewed PR, after branch comparison and current CI. The orchestrator owns master scheduling/assembly; Chat A owns story intelligence; Chat B owns mobile UI; Chat C owns generation hardware. This workstream does not authorize source resets, force pushes or deployment.
