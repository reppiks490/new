# Cinematic Orchestrator v1 — Design Specification

Date: 2026-10-22
Branch: `feat/cinematic-orchestrator-v1`
Base: `feat/private-mobile-video-studio`
Status: Design approved in chat; implementation not yet started on this branch.

## 1. Intent

Build a persistent long-form filmmaking layer on top of the existing private mobile video studio so the product stops treating video generation as isolated single-image, single-prompt jobs.

The user should be able to upload one or many reference images, enter a very long cinematic prompt, and have the application convert that prompt into a structured project containing scenes and shots that can be edited, regenerated, reordered, continuity-checked, rendered independently, and assembled into a long-form master timeline.

The initial target is a robust 10-minute project representation with no architectural dependency on a paid API. The user's current hardware constraint is a Nimo-brand Windows laptop previously observed exposing Intel UHD Graphics and no detected NVIDIA CUDA runtime, plus an iPhone used as the primary controller. The architecture therefore must keep expensive generation behind pluggable engine adapters while allowing all orchestration, metadata, editing, continuity state, queueing, and assembly logic to run locally.

## 2. Success criteria

The first implementation is successful when all of the following are true:

1. A user can create a cinematic project with a title, target runtime, aspect ratio, delivery FPS, delivery resolution target, and master prompt.
2. A project can contain multiple scenes, and each scene can contain multiple shots.
3. Each scene and shot can attach multiple reference-image IDs rather than a single global `image_id`.
4. A long prompt can be compiled into an editable shot graph without requiring an external LLM.
5. Explicit scene markers in the master prompt are preserved deterministically.
6. When no explicit markers exist, the compiler splits prose into coherent scene-sized chunks using punctuation, paragraph, and target-duration heuristics.
7. The compiler budgets shot durations so the project approximately reaches the requested runtime while respecting engine duration caps.
8. Continuity state is explicit and versioned: character, wardrobe, props, location, lighting, time-of-day, weather, camera language, and arbitrary notes.
9. A shot render request is created from project + scene + shot + continuity state + reference images, rather than from an unstructured project prompt alone.
10. Existing single-shot `/api/video/generate` behavior remains intact for backward compatibility.
11. The API exposes project CRUD, compile, render-plan inspection, and shot-level render submission.
12. No private prompt text is inserted into public media URLs or neutralized job labels.
13. The entire orchestration layer is fully testable with the existing fake video engine and does not depend on CUDA, paid APIs, or FFmpeg for unit tests.
14. The mobile UI can create/open projects, edit scene cards, inspect shots, attach references, and submit a selected shot to the existing render queue.
15. Delivery FPS/resolution are treated as finishing targets and are never falsely passed to a generation engine that does not support them.

## 3. Non-goals for v1

The first orchestrator version will not pretend to solve model-quality limits. Specifically:

- It will not guarantee Wan 2.2-class visual quality on Intel UHD hardware.
- It will not claim native 4K/8K or native 60/120 FPS when an engine does not provide them.
- It will not require or silently invoke paid cloud services.
- It will not attempt a single 10-minute generative inference call.
- It will not embed an autonomous external LLM as a required compiler dependency.
- It will not add unrelated 3D-studio refactors.

These are deliberate boundaries. The orchestrator is designed so stronger generation, interpolation, upscaling, audio, and verification backends can be added later without changing the project model.

## 4. Existing system constraints

The current video studio already provides:

- `/api/video/images` image upload and normalization.
- `/api/video/generate` single-shot queue submission.
- `/api/video/jobs` job persistence and polling.
- A video engine registry with capability declarations.
- An LTX local adapter plus a hermetic fake engine used in tests.
- Runtime reporting for GPU/CUDA/FFmpeg readiness.
- Private asset serving with `Cache-Control: no-store`.
- Token-protected remote API access and origin validation.
- iPhone-oriented private UI with prompt/media concealment and quick-hide controls.

The new subsystem should extend these primitives instead of replacing them.

## 5. Recommended architecture

### 5.1 Domain hierarchy

```text
CinematicProject
  ├── ProjectSettings
  ├── ContinuityBible
  ├── reference_image_ids[]
  └── Scene[]
        ├── SceneContinuityPatch
        ├── reference_image_ids[]
        └── Shot[]
              ├── prompt
              ├── negative_prompt
              ├── duration_seconds
              ├── camera
              ├── reference_image_ids[]
              ├── continuity_patch
              ├── transition_in/out
              └── render state
```

A project is the durable unit. A render job is ephemeral execution state tied back to a specific shot and a specific project revision.

Named reusable reference packs are intentionally deferred. v1 uses ordered image-ID lists at project, scene, and shot scope so the stored model has no undefined `ReferencePack` abstraction.

### 5.2 Separation of responsibilities

`app/video/cinematic_models.py`
- Pydantic domain models for projects, scenes, shots, continuity, and render plans.
- No storage or rendering code.

`app/video/cinematic_compiler.py`
- Pure deterministic prompt-to-scene/shot transformation.
- No database access.
- No network access.
- Produces a compile result that can be inspected and tested.

`app/video/cinematic_service.py`
- Project persistence, revision handling, compile application, capability negotiation, and shot-plan construction.
- Validates reference IDs against local assets before accepting a render plan.

`app/video/router.py`
- Adds cinematic endpoints while preserving existing single-shot endpoints.

`app/video/storage.py`
- Expands allowed record kinds for cinematic projects and optionally render-plan snapshots.

`app/studio/web/video-studio.js`
- Adds project/timeline mode while retaining the existing quick single-shot mode.

Tests are split across model, compiler, service, API, and browser-state behavior so failures identify one layer.

## 6. Data model

### 6.1 Project

Required fields:

- `id` — existing 32-character lowercase hex record ID.
- `revision` — positive integer incremented on every accepted mutation.
- `title` — 1..160 characters.
- `master_prompt` — up to 100,000 characters in v1.
- `target_duration_seconds` — 10..28,800 seconds.
- `delivery_fps` — integer, 1..120; finishing preference, not a claim of engine support.
- `delivery_resolution` — `480p | 720p | 1080p | 1440p | 2160p`; finishing preference, not a claim of engine support.
- `aspect_ratio` — normalized string such as `16:9`, `9:16`, `1:1`, `2.39:1`.
- `continuity_bible` — base continuity object.
- `reference_image_ids` — project-level ordered unique list.
- `scenes` — ordered list.
- `created_at` / `updated_at` — UTC ISO timestamps.

Generation-native FPS/resolution are not stored as the same fields. They are negotiated for each render plan from the selected engine capabilities.

### 6.2 Continuity bible

The continuity model contains explicit optional fields plus an extensible note map:

- characters
- wardrobe
- props
- location
- geography
- lighting
- time_of_day
- weather
- camera_language
- color_language
- physical_state
- story_state
- immutable_constraints
- freeform_notes

Continuity inheritance is additive:

```text
project bible
   + scene patch
      + shot patch
         = effective shot continuity
```

A child patch can override a key but cannot mutate the parent object in place.

### 6.3 Scene

- stable `scene_id` scoped to a project
- ordinal
- title
- synopsis
- source_text
- target_duration_seconds
- reference_image_ids
- continuity_patch
- shots

### 6.4 Shot

- stable `shot_id` scoped to a project
- ordinal
- title
- prompt
- negative_prompt
- duration_seconds
- seed
- camera_motion
- lens_mm optional
- framing optional
- motion_strength optional
- reference_image_ids
- continuity_patch
- transition_in
- transition_out
- engine_profile preference
- render metadata: latest job ID, latest asset URL, latest rendered project revision

## 7. Long-prompt compiler

The compiler must operate at zero cost and without requiring an LLM.

### 7.1 Explicit scene syntax

The compiler recognizes case-insensitive markers such as:

```text
SCENE 1: Rooftop
## Scene: Rooftop
[SCENE: Rooftop]
--- SCENE Rooftop ---
```

Explicit markers create hard scene boundaries and preserve the supplied titles.

### 7.2 Automatic decomposition

If explicit markers are absent, the compiler:

1. Normalizes whitespace while preserving paragraph boundaries.
2. Splits on paragraphs first.
3. Splits oversized paragraphs on sentence boundaries.
4. Groups adjacent segments toward a configurable target scene duration.
5. Avoids segments shorter than a configurable minimum unless they are the final segment.
6. Creates stable titles from the first meaningful clause rather than leaking the entire prompt into UI labels.

### 7.3 Duration budgeting

Inputs:

- project target duration
- number of scenes or compiler-derived chunks
- preferred shot duration
- engine maximum shot duration

Rules:

- No generated shot exceeds the selected engine's declared maximum duration.
- A scene may contain multiple shots.
- Shot durations sum approximately to the scene budget.
- Scene budgets sum exactly to the requested project target within floating point tolerance by adjusting the final shot.
- The compiler must not create a zero- or negative-duration shot.

For a 600-second target and a 10-second preferred shot duration, the result should be approximately 60 shots unless explicit scene structure produces a more suitable distribution.

### 7.4 Prompt isolation

Each generated shot prompt contains only:

- the local source segment
- inherited continuity summary
- scene objective
- explicit shot camera/action controls

The full master prompt is not blindly repeated into every engine call. This is a core protection against prompt contamination and instruction collisions.

## 8. Render-plan construction

A render plan is a pure snapshot derived from a project revision and shot.

Fields include:

- project ID + revision
- scene ID
- shot ID
- effective prompt
- negative prompt
- effective continuity object
- resolved ordered reference-image IDs
- requested shot duration/profile
- `generation_fps`
- `generation_resolution`
- `delivery_fps`
- `delivery_resolution`
- optional previous-shot bridge asset
- optional next-shot target frame reference in future versions

Reference resolution order:

1. project references
2. scene references
3. shot references

Duplicates are removed while preserving first occurrence.

The plan builder must reject missing local reference IDs before queue submission.

### 8.1 Engine capability negotiation

Delivery settings and generation settings are deliberately separate.

For a selected engine:

- `generation_resolution` is the highest supported native resolution that does not exceed the numeric delivery target; if none is at or below the delivery target, use the engine's lowest supported resolution.
- `generation_fps` is the highest supported native FPS that does not exceed `delivery_fps`; if none is at or below the delivery target, use the engine's lowest supported FPS.
- Shot duration must be clamped by compiler construction, not silently truncated at render time.
- Unsupported camera or motion controls still fail explicitly through the existing engine validation layer.

Examples:

- Delivery target 2160p/120 FPS + engine supports 1080p/60 FPS => generate 1080p/60 FPS and retain 2160p/120 FPS as finishing targets.
- Delivery target 1080p/24 FPS + engine supports 720p/1080p and 24/30 FPS => generate 1080p/24 FPS.

Interpolation/upscaling are future finishing stages. v1 only preserves the requested delivery target and does not falsely label generated media as native delivery quality.

## 9. API design

All new routes remain under `/api/video` and inherit existing authentication/origin protection.

### Projects

- `POST /api/video/projects`
  - create project
- `GET /api/video/projects`
  - list projects
- `GET /api/video/projects/{project_id}`
  - fetch one project
- `PUT /api/video/projects/{project_id}`
  - replace mutable project fields using optimistic revision checking

### Compilation

- `POST /api/video/projects/{project_id}/compile`
  - deterministic compile from master prompt
  - body includes preferred shot seconds and optional engine name/capability override
  - returns new project revision + compiler diagnostics

### Render plan

- `GET /api/video/projects/{project_id}/scenes/{scene_id}/shots/{shot_id}/plan`
  - inspect exactly what would be sent to the engine

### Render shot

- `POST /api/video/projects/{project_id}/scenes/{scene_id}/shots/{shot_id}/render`
  - validates project revision
  - resolves plan
  - maps generation-native fields to the existing `VideoGenerationRequest`
  - retains delivery targets as project metadata for later finishing stages
  - submits through the existing video job queue
  - persists the returned job ID into shot render metadata

The first version renders one selected shot at a time. Batch scheduling is deferred until the single-shot project path is correct and recoverable.

## 10. Backward compatibility

Existing routes remain unchanged:

- `/api/video/images`
- `/api/video/generate`
- `/api/video/jobs`
- `/api/video/privacy`
- `/api/video/assets/*`

The current quick single-shot UI remains available. Project mode is additive.

## 11. Storage and revisions

Add record kind:

- `video_project`

Every project write increments `revision`.

Update operations supply `expected_revision`. If the stored revision differs, the API returns HTTP 409 rather than silently overwriting newer edits from another phone/browser tab.

Project records remain in the existing SQLite `records` table to avoid a migration dependency in v1.

No prompt content is written into filenames. Media assets keep opaque random IDs.

## 12. Mobile UI design

Project mode adds four panes/states while retaining the existing privacy system:

1. **Project list** — neutral titles when privacy mode is active.
2. **Project editor** — master prompt, duration, format, reference images.
3. **Scene timeline** — collapsible scene cards with duration totals.
4. **Shot inspector** — prompt, continuity patch, references, camera controls, render button, latest result.

Key operations:

- New project
- Compile prompt
- Add/delete/reorder scene
- Add/delete/reorder shot
- Split shot
- Duplicate shot
- Attach reference image
- Render selected shot
- Open latest result

The first UI increment may omit drag-and-drop reordering and use explicit move up/down buttons for reliability on iPhone.

## 13. Error handling

- Invalid/missing project: 404
- Revision conflict: 409
- Missing reference asset: 422
- Unsupported engine control: 422 using existing engine validation
- No available engine: 503 using existing semantics
- Compile input too large/invalid: 422
- Compiler internal invariant failure: 500 with generic client message; detailed server log only

No partial write is accepted if project validation fails.

## 14. Security and privacy

The new subsystem inherits existing bearer-token and origin checks.

Additional rules:

- Prompt and continuity content never appears in asset URLs.
- `GET /projects` may return neutral summaries under privacy mode in a later hardening pass; v1 relies on existing authenticated API boundary and client concealment.
- Render jobs store IDs and status but do not duplicate master prompts into job-list records.
- Reference paths are never supplied by the client; only opaque asset IDs are accepted.
- Asset IDs are validated through the existing path-safety layer.

## 15. Testing strategy

### Model tests

- reject duplicate scene/shot IDs
- reject invalid durations
- reject overlong master prompts
- continuity patch merge is non-mutating
- reference ID deduplication preserves order
- delivery targets remain distinct from generation-native settings

### Compiler tests

- explicit scene markers create exact boundaries
- paragraph-based fallback decomposition
- very long paragraph sentence splitting
- 600-second target produces legal shot durations
- final duration sum matches target
- engine max duration is never exceeded
- deterministic: same input yields identical scene/shot structure
- empty/whitespace prompt rejected

### Service tests

- create/read/update project
- revision increments
- stale expected revision returns conflict
- render plan resolves inherited continuity
- missing reference IDs rejected
- project/scene/shot reference order is stable
- 2160p/120 delivery target negotiates down to actual engine-native capability without altering stored delivery targets

### API tests

- authentication reused
- project CRUD
- compile endpoint
- plan endpoint
- render selected shot through fake engine
- existing `/generate` tests remain unchanged

### Browser/JS tests

- privacy mode conceals project titles where configured
- selected project survives re-render in client state
- compile response renders scenes/shots correctly
- selected shot render submits only the shot plan, not full project prompt

## 16. Acceptance gates

### Gate A — pure domain

All model/compiler tests pass with no FastAPI server and no GPU dependencies.

### Gate B — persistence/API

A 10-minute text prompt can be compiled into a persisted project and fetched back with exact deterministic scene/shot IDs and a total shot duration of 600 seconds ± 0.001.

### Gate C — render integration

One compiled shot can be rendered with `FakeVideoEngine`, producing a successful existing video job while preserving project/scene/shot linkage.

### Gate D — mobile flow

From the browser UI, a user can create a project, upload at least two references, compile the master prompt, select a shot, and submit that shot without using developer tools.

### Gate E — regression

All pre-existing video, image, privacy, startup, and repository-hygiene tests continue to pass.

## 17. Future extensions enabled by this design

These are not required for v1, but the interfaces deliberately permit them:

- named reusable reference packs
- automatic first/last-frame bridge extraction
- VLM continuity scoring
- face/identity consistency scoring
- optical-flow and interpolation workers
- super-resolution workers
- audio dialogue/music/SFX timeline tracks
- lip-sync adapters
- multi-engine candidate generation and ranking
- batch scene scheduler with dependency graph
- checkpoint/resume for long projects
- EDL/OTIO export
- FFmpeg master assembly
- cached reference embeddings
- local or remote LLM-assisted scene compiler as an optional enhancement
- render-farm adapters if free or paid compute becomes available later

## 18. Chosen approach and rejected alternatives

### Chosen: persistent project graph over the existing engine queue

Why:
- preserves current working single-shot infrastructure
- isolates orchestration from model availability
- works at zero cost
- supports the user's phone-first workflow
- scales naturally from two shots to hundreds
- makes selective re-render possible

### Rejected: encode the whole film into one giant prompt/job

Reason:
- violates current engine duration constraints
- creates prompt contamination
- makes selective correction impossible
- makes continuity drift harder to detect and repair

### Rejected: require an external LLM for scene decomposition

Reason:
- conflicts with the zero-dollar requirement
- introduces network/privacy dependency
- makes deterministic tests difficult

Optional LLM assistance can be added later behind a compiler interface without changing stored project data.

## 19. Implementation order

1. Domain models and pure compiler.
2. Persistence/service layer with revision semantics and capability negotiation.
3. API endpoints and fake-engine shot rendering.
4. Mobile project/timeline UI.
5. Regression and security hardening.
6. Only after v1 is stable: batch rendering, stitching, interpolation, verification, and advanced backends.

This order intentionally proves the long-form data model before adding visual complexity.
