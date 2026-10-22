# Helper Bot 2 — Cinematic Timeline Preflight

**Repository:** reppiks490/new
**Base branch:** feat/cinematic-orchestrator-v1
**Work branch:** chatgpt/cinematic-timeline-quality-helper2-20261022

## Scope and ownership

This is a **standalone, additive** metadata inspection layer for long-form filmmaking. It does not modify the existing render queue, project persistence, asset serving, API routes, FFmpeg assembly, or UI files currently owned by other agents.

- Implementation: app/video/cinematic_quality.py
- Tests: tests/test_cinematic_quality.py
- Entry point: audit_timeline(project) -> TimelinePreflight
- JSON-safe result: audit_timeline(project).as_dict()

## Checks

- Missing scenes or scenes containing no shots: **error**
- Individual shots lacking any inherited reference-image ID: **error**
- Sum of shot durations vs scene budget: **error**
- Sum of shot durations vs project target: **error**
- Override of an inherited non-null immutable_constraints value: **error**
- Mismatched scene ordinal vs list order: **warning**
- Non-increasing shot ordinals within a scene: **warning**

structurally_ready is true only when none of these metadata checks returns an error. It is not an engine-capability check, a guarantee that media files exist, an artistic quality score, or proof that FFmpeg can assemble a film.

## Security and privacy properties

- No API tokens, filepaths, network calls, model inference, or media reads.
- Findings contain only stable codes and opaque scene/shot IDs.
- Private prompt text, project/shot titles, story notes, and immutable constraint values never appear in results.
- This function performs no writes and can safely run on in-memory projects.

## Integration path

A project-status endpoint or shot inspector can call:

~~~python
from app.video.cinematic_quality import audit_timeline
report = audit_timeline(project)
response = report.as_dict()
~~~

Call the existing reference-asset checks and engine capability validation separately before queueing render jobs. Treat continuity override errors as editorial approval gates; this checker intentionally does not rewrite the project's choices.

## Verification and baseline warning

Run the isolated suite:

~~~bash
pytest -q -W error tests/test_cinematic_quality.py
~~~

Run the full repository matrix before integration. At branch creation, the upstream feat/cinematic-orchestrator-v1 baseline already failed four master-assembly tests because production names were absent: render_project_missing, project_render_status, MasterAssemblyNotReady, and _run_master_ffmpeg. Those are owned by the separate master-assembly workstream and are not changed here. The Python 3.11 cancellation in previous runs was concurrency-related; a cancelled job is not a passing job.
