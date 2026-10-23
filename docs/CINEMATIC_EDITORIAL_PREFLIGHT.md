# Cinematic editorial preflight — Helper Bot 3

This is an isolated, zero-network contribution originally based on
`feat/cinematic-orchestrator-v1`. PR #9 now targets
`chatgpt/cinematic-master-assembly-20261022` to validate against the lead's
implemented batch/master services; neither parent branch was rewritten. It does **not** change the existing
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
- Per-scene half-open spans report authored shot count, expected/actual frames,
  and signed scene-budget differences. Empty scenes remain explicit diagnostics.
- Each clip has start/end integer-frame non-drop timecodes. The `clip_at_frame`
  method finds the authored shot for an exact frame, including cut boundaries;
  out-of-range seeks are rejected.
- The canonical `timeline_digest_sha256` tracks project ID, revision, delivery
  FPS, target frames and scene/shot frame intervals. Its identity matches the
  independent **Helper 4** QA-only frame oracle. It is not a media-content
  hash, cryptographic asset attestation, or approval to reuse an output file.
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
migrations. The lead's merge/target branch is not rewritten. Merge only after
fresh *combined-head* Python 3.11/3.12, browser regression and Docker CI
succeed and security/release blockers are separately dispositioned. This helper
does not own the lead branch or the CI repair.


## Non-destructive director's-cut planning (integration extension)

The optional `app/video/cinematic_directors_cut.py` adds a purely editorial
composer. It never writes the project, touches job records, reads source media,
modifies file paths, invokes render engines or claims the final video exists.

```python
from app.video.cinematic_directors_cut import CutSelection, plan_directors_cut
from app.video.cinematic_service import get_project

project = get_project(project_id)
first, second = project.scenes[0].shots[:2]
cut = plan_directors_cut(project, [
    CutSelection(first.shot_id, source_in_frame=0, source_out_frame_exclusive=48),
    CutSelection(second.shot_id),  # full clip
    CutSelection(first.shot_id, source_in_frame=48),  # intentional reuse
])
print(cut.frame_count, cut.cut_digest_sha256)
print(cut.segment_at_frame(0).shot_id)
snapshot = cut.to_dict()
```

### Frame conventions

- Source in/out offsets are local to the chosen shot, **not** global frame
  addresses. Every interval is half-open `[in, out)`.
- All offsets are **integer delivery-frame positions**. Frames must exist in
  the original editorial EDL, and every retained segment has at least one frame.
- Repetitions and arbitrary reordering are deliberate. The only excluded
  frames are those explicitly trimmed or omitted by the selected intervals;
  no **additional** frames are inserted, dropped or stretched.
- `scene_changed` and `continuity_changed_fields` flag visible editorial
  risks after reordering, without disclosing screenplay, dialogue, wardrobe
  descriptions, location names, or any continuity values.
- Transition presence is only propagated if the selected segment includes
  the original clip's start/end boundary. These are *intent flags*, never
  automatic optical transitions or assurance that media processing occurred.
- Each cut binds to the original project ID/revision and source timeline
  digest. A separately supplied source timeline is rejected unless it exactly
  matches a freshly computed source EDL. A cut digest protects reproducibility
  of metadata decisions, **not source media authenticity**.
- Archived cut metadata is versioned (`schema_version=1`) and can be validated
  with `verify_directors_cut(project, cut)`, which reconstructs and compares
  every public field against the current project revision. Tampering or stale
  revisions fail explicitly. This is **not** a cryptographic signature or a
  verification that physical video frames exist.
- For storage/reload, serialize `cut.to_dict()` to JSON, parse the saved JSON,
  then call `restore_directors_cut(project, decoded_payload)`. The loader
  reconstructs canonical shot selections from current authoritative project
  state and rejects changed fields, injected keys, altered hashes, malformed
  frame offsets or obsolete revisions. Serialized object data is never blindly
  trusted or executed. This still cannot establish media authenticity.

### Safe next integration points

An authenticated mobile project editor can preview a cut's metadata, require
explicit user confirmation to save it as a named edit version, and separately
submit conform jobs that validate real source file FPS/duration/codec, media
bytes and access permissions. No such conform worker or saved-cut endpoint is
implemented here. In particular, a metadata-perfect cut is **not a finished
film**, and director-cut planning must never silently enqueue generation or
charge a provider.

New extension files in integration PR #18:

- `app/video/cinematic_directors_cut.py`
- `tests/test_cinematic_directors_cut.py`

These changes do not modify the original authorship PR #9, the lead's
master-assembly source, or Helper 1/2/4 code. Full current-head CI must pass
before integration.


## Revision impact: avoid stale-shot reuse after edits

`app/video/cinematic_revision_impact.py` provides a conservative, read-only
`analyze_cinematic_revision(before, after)` report for an older and newer
revision of **the same persisted project**. It does not retrieve records,
read files or ask a render engine to run.

```python
from app.video.cinematic_revision_impact import analyze_cinematic_revision

impact = analyze_cinematic_revision(old_project_snapshot, current_project)
for shot in impact.shots:
    if shot.requires_new_render:
        print(shot.shot_id, shot.reason_codes)
print(impact.requires_recompile, impact.requires_master_reassembly)
```

The comparison understands changes in shot-local prompts, negative prompts,
durations, seeds, motion controls and profiles, inherited project/scene/shot
continuity, *ordered* inherited image-reference IDs, scene-specific job linkage,
scene/shot sequence and delivery FPS/resolution/aspect ratio. It reports opaque
shot/scene IDs and neutral reasons, **never** raw prompts, media paths, image
reference IDs, secret creative values or content-derived hashes.

- Render-affecting changes are reported per shot. Newly added shots need
  rendering; removed shots do not. Reordering an unchanged shot may require
  re-assembly but does not, by itself, require generating it again.
- Delivery FPS/resolution changes conservatively flag all retained shots,
  because actual provider-native choices may depend on target delivery settings.
  The report cannot prove a previous source is compatible without engine data.
- Master screenplay changes and source/scene timing changes require
  re-compilation review. They do not automatically claim unchanged compiled
  shot prompts were affected; a new compilation can change shot IDs or prompts.
- Edits to `lens_mm`, `framing`, or transition intent explicitly require
  creative review, because the current generation adapter does not guarantee
  applying these fields. Re-rendering alone is **not a substitute** for
  implementing missing adapter or finishing effects.
- Updated project titles, job-bookkeeping fields and timestamps do not
  invalidate a rendered source by themselves.
- `unchanged_render_input_shots` means **only** unchanged *known metadata
  inputs*, including shots merely reordered or renamed. `changed_shots` counts
  any detected metadata reason; these counts can overlap, so do not add them
  together to estimate rendering cost. It is never permission to reuse persisted footage or declare it
  current. Image/media bytes can change under the same opaque asset ID; current
  data files, prompt-packing rules, provider versions, external capabilities,
  storage integrity, and job-link CAS checks are outside this advisory layer.

The owner-controlled render queue must compare trusted current input and
source-byte provenance, confirm project revision and job linkage atomically,
and fail closed on stale inputs (see lead-owned issue #19). This module is an
explicit planning/diagnostics aid for that work, not a replacement for it.

Files introduced in this revision-impact extension:

- `app/video/cinematic_revision_impact.py`
- `tests/test_cinematic_revision_impact.py`

The lead retains the authority and responsibility to implement safe actual
job invalidation and render scheduling. There is no live/billable model call,
database write, provider connection or new production endpoint in this patch.
