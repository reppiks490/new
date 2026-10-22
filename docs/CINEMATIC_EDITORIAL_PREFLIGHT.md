# Cinematic editorial preflight — Helper Bot 3

This is an isolated, zero-network contribution based on
`feat/cinematic-orchestrator-v1`. It does **not** change the existing
cinematic project CRUD, shot rendering, or master assembler.

## Purpose

A long-form master can look plausible while silently drifting from its
requested duration. Clip-local float rounding, incidental sorting by ordinals,
and unreported continuity changes make this difficult to diagnose. The
`preflight_editorial_timeline` function provides a deterministic, frame-based
edit decision list for the current project revision before media assembly.

## Example

```python
from app.video.cinematic_editing import preflight_editorial_timeline
from app.video.cinematic_service import get_project

project = get_project(project_id)
report = preflight_editorial_timeline(project)
print(report.target_frames, report.actual_frames)
print(report.warnings)
edl = report.to_dict()
```

For a 600-second, 120-FPS project with sixty 10-second shots, the expected
duration is 72,000 frames. The EDL preserves authored list order. Start/end
frames are half-open intervals, so clip `[0, 1200)` contributes precisely
1,200 frames.

## Guarantees

- Frame boundaries are rounded once from cumulative Decimal time rather than
  summing per-shot rounded durations. No implicit resampling or stretching.
- Target and actual duration remain separately visible. A discrepancy produces
  a warning and signed frame difference, never an invented perfect total.
- Sub-frame shots that cannot occupy one whole delivery frame are rejected.
- Scene and shot ordinal inconsistencies are detected without reordering.
- Effective continuity inheritance is inspected between consecutive shots;
  only changed **field names** are reported, not sensitive field values.
- Project content, prompts, source-media URLs and credentials never enter the
  EDL.
- Transition intent is reduced to presence flags, never free-text values. These
  flags **do not** assert that a
  video crossfade, cut, frame bridge, or any other physical effect was rendered.
- Neither an EDL nor the absence of warnings establishes asset integrity,
  audio sync, codec compatibility, render success, or readiness to assemble.
  Those are separate master-verification gates.

## Integration recommendation

Once core orchestrator work is stable, call this preflight immediately before
render-all / master assembly planning. Expose the warnings in the authenticated
mobile timeline editor and store the EDL alongside the master as a provenance
snapshot keyed by project ID and revision. Never treat a clean planning report
as proof that the requested quality, native FPS, or resolution was delivered.

## Scope and verification

Files in this helper contribution:

- `app/video/cinematic_editing.py` — standalone frame-accurate report
- `tests/test_cinematic_editing.py` — deterministic tests
- this guide

No new dependencies, paid APIs, GPU, FFmpeg, browser storage, or schema
migrations. Merge only after the parent cinematic branch is stable and the
full CI matrix passes, or after a documented pre-existing CI failure is
resolved. This helper does not own the lead branch or the CI repair.
