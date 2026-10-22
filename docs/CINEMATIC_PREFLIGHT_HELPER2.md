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


## Helper 2 extension — offline whole-project engine capability preflight

- Implementation: app/video/cinematic_capability_preflight.py
- Tests: tests/test_cinematic_capability_preflight.py
- Entry point: audit_engine_capabilities(project, capabilities)
- Input is an explicit EngineCapabilities snapshot, NOT an engine/registry or live GPU call.

This read-only gate checks engine availability advertisement, usable FPS/resolution
declarations, duration min/max, the existing VideoGenerationRequest native 60-FPS
and 1-to-30-second limits, and every shot's profile, camera motion, and motion
strength against an explicitly selected engine. It reports native/delivery
differences without describing interpolation or upscaling as already performed.
It preserves each shot's opaque ID without disclosing camera text, private story
notes, titles, prompts, engine details or private files.

**Meaning of capability_ready:** all stored shots are *metadata-compatible* with
one declared engine at inspection time. This is not proof the backend remains
available, the reference files exist, video is renderable, or finishing is
installed. Pair with audit_timeline for structure and with actual storage checks,
runtime engine selection, rendering and ffprobe before a live production claim.

Example (no model execution or charge):

~~~python
from app.video.cinematic_capability_preflight import audit_engine_capabilities
from app.video.cinematic_quality import audit_timeline

timeline = audit_timeline(project)
capability = audit_engine_capabilities(project, selected_capabilities)
metadata_ready = timeline.structurally_ready and capability.capability_ready
summary = {
    "metadata_ready": metadata_ready,
    "timeline": timeline.as_dict(),
    "capabilities": capability.as_dict(),
}
~~~

Do not expose a misleading global 'ready to render' status solely from this
metadata snapshot; media existence and current runtime readiness remain
separate checks. Source-image validity is still authoritative in the existing
render service. Helper 3 PR #9 owns editorial frame EDL and Helper 4 PR #12
owns an independent acceptance oracle: neither implementation is replaced.

At addition time, branch inherited four master-assembly test failures from
the original feature baseline. Those four functions were implemented by lead
PR #8 and must be integrated non-destructively. Never skip their tests.
