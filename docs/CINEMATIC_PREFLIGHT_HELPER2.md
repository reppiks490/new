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


## Helper 2 extension — trusted-local reference integrity preflight

The additive module app/video/cinematic_reference_preflight.py offers a third,
explicitly opt-in check: audit_reference_files(project, workspace=trusted_local_path).
It reads existing local PNGs (unlike the two pure-metadata checks) but has
**no network calls, no external services, no project writes, and no directory
creation**. Do not expose the workspace argument as an arbitrary remote user
supplied path; it must be a **server-selected, trusted local studio workspace**.

The auditor examines **every distinct inherited image ID** exactly once, maps
errors to every affected shot, and rejects:

- missing or unreadable normalized PNG files;
- invalid/corrupt/truncated PNG contents;
- files with the wrong actual encoded format despite a .png filename;
- images beyond the existing 20-megapixel upload bound;
- unsafe symlinks or traversals in the workspace's asset directory;
- missing workspace/directory, empty timelines or shots with no reference IDs.

Reference IDs are guarded again in case an in-memory Pydantic model_copy
bypassed normal validation. Results disclose only neutral error codes and
opaque scene/shot IDs—never private pixel contents, file paths, source IDs,
screensplays, engine details or content hashes. Repeated references are decoded
only once, with diagnostics still reported on *every* affected shot.

Example server-side usage:

~~~python
from pathlib import Path
from app.video.cinematic_reference_preflight import audit_reference_files

source_report = audit_reference_files(project, workspace=Path(trusted_studio_workspace))
all_preflight_metadata_passed = (
    audit_timeline(project).structurally_ready
    and audit_engine_capabilities(project, selected_capabilities).capability_ready
    and source_report.references_ready
)
~~~

**Critical evidence boundary:** File readiness is a moment-in-time observation,
not a durable guarantee that assets stay unchanged between inspection and
render. The service must perform its own authoritative path, existence and
capability validation at enqueue time. A genuine render, source hash/probe,
FFmpeg playback and the owner's iPhone verification remain distinct release
gates. This check does not duplicate Helper 3's frame EDL or Helper 4's
independent frame oracle, and does not change lead's service/router.
