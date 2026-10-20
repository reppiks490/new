# Private Mobile Image-to-Video Studio Design

Date: 2026-10-20
Repository: `reppiks490/new`
Status: design specification

## 1. Intent

Add a native image-to-video subsystem to the existing Forma browser studio. The primary user experience is an iPhone-first private web interface that uploads a source image, accepts a motion prompt, runs local/open-weight video inference on the owner's PC/GPU, and returns an MP4 for preview and download.

Success means:

- no per-generation API credits, inference tokens, or paid remote generation dependency;
- the iPhone is a controller/client, while heavy inference runs on the owner's PC;
- the existing 3D studio remains functional and unchanged unless integration requires a narrow shared primitive;
- generated media remains private to the local workspace unless the owner explicitly downloads/exports it;
- remote use is protected by the studio's existing bearer-token/Tailscale-style private access model;
- the mobile UI includes shoulder-surfing privacy controls so prompts and previews are not plainly visible to someone sitting nearby;
- the video engine is modular so the strongest locally runnable model can be selected after GPU/VRAM detection without redesigning the UI or API.

This subsystem is for lawful adult use. It must not add functionality intended to create sexual depictions of minors or non-consensual sexual deepfakes of real people.

## 2. Existing System Constraints

The repository already provides:

- FastAPI server and browser studio;
- private API middleware with bearer-token protection for remote access;
- local-only fallback when no token is configured;
- image upload validation and normalization;
- SQLite-backed job persistence;
- background generation workers;
- workspace-scoped asset storage;
- browser-side project/status UI.

The new subsystem should reuse these capabilities rather than create a second application stack.

## 3. Chosen Architecture

### 3.1 High-level flow

```text
iPhone Safari / installed PWA
        |
        | private HTTPS/Tailscale + bearer token
        v
Forma FastAPI server (`reppiks490/new`)
        |
        +--> video API + persistent job record
        |
        +--> local video worker
                |
                +--> hardware capability detection
                +--> selected local I2V adapter
                +--> frames / encoding
                v
             MP4 asset
        |
        v
mobile preview / download / private gallery
```

### 3.2 Separation of responsibilities

The 3D studio's existing `/api/studio/generate` path remains responsible for 3D-provider generation. Video generation gets a separate `/api/video` namespace and worker implementation. This prevents video-specific runtime state, model loading, and MP4 assets from coupling to the existing GLB provider flow.

## 4. Backend Components

### 4.1 `app/video/router.py`

Owns the public API contract:

- `GET /api/video/capabilities`
- `POST /api/video/images`
- `POST /api/video/generate`
- `GET /api/video/jobs`
- `GET /api/video/jobs/{id}`
- `GET /api/video/assets/{filename}`
- `GET /api/video/privacy`
- `PUT /api/video/privacy`

The API must never return secret environment-variable values.

### 4.2 `app/video/models.py`

Pydantic request/response models for:

- video generation request;
- model/runtime capability report;
- privacy preferences;
- job/public status payload.

Generation request fields should include at minimum:

- `image_id`
- `prompt`
- `model` or `engine_profile`
- `seed`
- `duration_seconds`
- `fps`
- `resolution` or width/height preset
- `motion_strength` when supported
- optional camera-motion preset

Unsupported controls must be rejected or ignored explicitly per adapter capability; the UI must not pretend every model supports every control.

### 4.3 `app/video/runtime.py`

Detects local execution capability without requiring paid providers:

- NVIDIA GPU presence;
- CUDA availability;
- GPU name;
- VRAM total/free when detectable;
- PyTorch CUDA readiness;
- FFmpeg availability;
- installed/available local model adapters;
- model-weight presence;
- blockers and recommended engine profile.

The capability endpoint should remain safe to expose to the authenticated owner and must not expose host secrets.

### 4.4 `app/video/engine.py`

Defines an adapter boundary such as:

```python
class ImageToVideoEngine(Protocol):
    name: str
    def capabilities(self) -> EngineCapabilities: ...
    def generate(self, request: VideoGenerationInput, progress: Callable[[...], None]) -> Path: ...
```

Initial implementation should support one verified local engine, selected after hardware detection. The architecture must allow LTX-family, Wan-family, or another open-weight local I2V implementation to be added without changing the HTTP contract.

The code must not require LTX API keys or another metered generation API.

### 4.5 `app/video/jobs.py`

Video jobs run outside request threads. Job state machine:

```text
queued -> loading -> generating -> encoding -> succeeded
                                   \-> failed
```

Persist:

- job ID;
- created/updated timestamps;
- status/stage;
- engine name/version/profile;
- seed and generation parameters;
- input image asset ID;
- output video asset ID when successful;
- coarse progress;
- sanitized error text.

A restart must mark active local jobs interrupted rather than silently resubmitting them.

### 4.6 Storage

Extend the existing storage abstraction rather than bypassing it.

Required asset extensions:

- PNG for normalized source images/posters;
- MP4 for generated video;
- optional JSON sidecar metadata if needed internally.

Path validation must preserve the existing ID-based anti-traversal model. No user-supplied filename should determine a filesystem path.

## 5. Local Inference Strategy

### 5.1 No-metered-inference requirement

Generation must run against model weights available locally on the PC. Authentication may be required once to download gated model weights from Hugging Face, but the generation loop must not call a paid inference endpoint or consume per-video credits.

### 5.2 Hardware-adaptive selection

Do not hard-code a heavyweight model before the owner's GPU/VRAM is known. Implement runtime detection first and use profiles:

- `low_vram`
- `balanced`
- `high_quality`

The selected adapter must document minimum VRAM, expected offloading behavior, storage footprint, and tested resolution/duration envelope.

If the hardware is insufficient, the UI must report the blocker instead of falling back to a paid provider.

### 5.3 Model loading

Use lazy singleton loading per worker process. Heavy weights must not load at module import or server startup unless explicitly configured for warm start.

The model cache path should be configurable under the existing workspace or a dedicated model directory outside version control.

## 6. Mobile-First UI

Add a new `Video` panel to the existing studio navigation rather than replacing the 3D workspace.

The video screen is optimized for iPhone portrait use and contains:

- image picker/upload;
- source preview;
- motion prompt;
- engine/profile selector;
- duration/FPS/resolution controls constrained by runtime capability;
- seed/randomize control;
- generate button;
- current job progress;
- MP4 preview;
- download/share action;
- recent video gallery.

The UI must remain usable on desktop as well.

## 7. Shoulder-Surfing Privacy Mode

Privacy Mode protects the visible mobile interface from casual nearby viewing. It is not an anti-forensics system and does not promise invisibility to an administrator with access to the device or server.

Default behavior when Privacy Mode is enabled:

- source image preview is strongly blurred;
- motion prompt is visually masked;
- generated video poster/thumbnails are blurred;
- recent-job cards use neutral labels such as `Project 12`;
- raw prompt text is omitted from visible job cards;
- sensitive previews require explicit reveal;
- application backgrounding immediately re-hides sensitive content.

### 7.1 Reveal interaction

Support press-and-hold reveal for images/prompts where practical on touch devices. Releasing the gesture restores masking. Also provide an accessible explicit reveal button for users who cannot use hold gestures.

### 7.2 Quick Hide

A persistent Quick Hide control immediately switches the video panel to a neutral workspace screen and removes sensitive media/prompt content from the visible DOM state where practical. Returning to the private view requires the normal unlock/reveal flow.

Quick Hide is a UI privacy feature, not a mechanism for deleting logs, falsifying system state, or hiding activity from device administrators.

### 7.3 Resume/idle lock

Configurable defaults:

- privacy mode on;
- prompt masking on;
- media blur on;
- quick hide on;
- 30-second idle lock;
- re-hide on `visibilitychange`/background;
- neutral project names on.

For mobile re-entry, support a local session PIN initially. WebAuthn/passkey can be added if testing confirms reliable iOS behavior in the deployment mode.

Do not store the studio bearer token in persistent browser storage by default; preserve the existing in-memory/session-oriented approach unless explicitly changed in a separate security review.

## 8. Security and Privacy

Reuse the existing server middleware for `/api/*` protection. Remote API access requires the configured studio token; local loopback may operate without it under the repository's current behavior.

Additional requirements:

- never log authorization headers or secrets;
- sanitize exception text before persistence;
- reject oversized/invalid uploaded files;
- validate MIME/container before serving generated files;
- set video responses to an appropriate media type;
- prevent path traversal/symlink escape;
- do not auto-upload source or generated media to cloud storage;
- do not auto-save generated media to the iPhone Photos library;
- exports/downloads are explicit user actions.

## 9. Integration With Existing Studio

`app/studio/server.py` should include the video router and retain current middleware.

`app/studio/web/index.html` gains a `Video` navigation item. Video-specific browser code should live in focused modules (`video-studio.js`, `privacy-mode.js`) rather than expanding the already-large `app.js` indefinitely.

Existing 3D routes, model library, character editing, GLB export, and provider integrations must continue to function.

FLUX 3 Image Klein may later be exposed as an optional still-image generation/editing tool that can produce a source frame for the video workflow. It is not the image-to-video engine.

## 10. Configuration

Proposed non-secret settings:

```env
CHARACTER3D_VIDEO_ENABLED=1
CHARACTER3D_VIDEO_MODEL_DIR=./weights/video
CHARACTER3D_VIDEO_OUTPUT_DIR=
CHARACTER3D_VIDEO_PRIVACY_DEFAULT=1
CHARACTER3D_VIDEO_IDLE_LOCK_SECONDS=30
CHARACTER3D_VIDEO_QUICK_HIDE_ENABLED=1
CHARACTER3D_VIDEO_REQUIRE_UNLOCK_ON_RESUME=1
```

Existing `CHARACTER3D_STUDIO_TOKEN` remains the server/API access credential.

No paid inference API key is part of the required video configuration.

## 11. Error Handling

The UI should distinguish:

- no compatible GPU/runtime;
- missing model weights;
- insufficient VRAM;
- model initialization failure;
- generation failure;
- FFmpeg/encoding failure;
- interrupted worker/restart;
- output validation failure.

Errors should be actionable and must not leak credentials or internal sensitive paths unnecessarily.

## 12. Testing Strategy

### Backend tests

- video request validation;
- invalid/missing source image rejection;
- unauthenticated remote API rejection using existing middleware behavior;
- local capability report with and without CUDA mocked;
- job state transitions;
- restart interruption behavior;
- storage path and extension validation;
- MP4 serving content type;
- secret redaction from failures;
- adapter capability enforcement;
- no paid-provider fallback.

### Frontend tests

Use the repository's existing JavaScript test style where practical:

- privacy mode masks prompt and image;
- hold/reveal state returns to hidden on pointer/touch release;
- `visibilitychange` re-hides content;
- quick hide removes sensitive UI from view;
- neutral labels are used while privacy mode is active;
- controls disable unsupported model parameters;
- generation/job polling renders the correct states.

### Regression tests

Existing studio tests must continue to pass. Add a focused smoke test proving that the 3D studio endpoints remain available after the video router is mounted.

## 13. Rollout Order

1. Add video package, models, storage support, router skeleton, and capability detection.
2. Add tests for API/security/storage behavior.
3. Add mobile Video panel and privacy-mode state machine with tests.
4. Add local engine adapter interface and deterministic fake engine for test/dev.
5. Detect the owner's GPU/VRAM and select the first production local I2V adapter.
6. Integrate/download verified model weights and validate one end-to-end image-to-MP4 generation on the target PC.
7. Validate iPhone/Tailscale access, shoulder-surfing privacy behavior, download, and restart recovery.
8. Only after the core I2V path is stable, optionally connect FLUX 3 Klein or existing 3D assets as source-image helpers.

## 14. Non-goals for v1

- paid cloud video providers;
- public multi-user hosting;
- account/billing systems;
- anti-forensics or covert deletion;
- automatic iCloud/Photos synchronization;
- GLB generation as part of the video critical path;
- training/fine-tuning video models.

## 15. Acceptance Criteria

The v1 build is complete when:

1. the existing Forma studio still starts and existing core tests pass;
2. an authenticated iPhone can open the Video panel through the private connection;
3. a PNG/JPEG/WebP can be uploaded and normalized;
4. a motion prompt and supported generation settings can be submitted;
5. the local PC performs image-to-video inference without a metered inference API;
6. job progress survives normal polling and interrupted jobs are marked safely after restart;
7. a valid MP4 is persisted, previewable, and explicitly downloadable;
8. Privacy Mode masks prompts and previews, supports quick hide, and re-hides on background/resume;
9. no secret/token value is exposed in API payloads or persisted error messages;
10. there is no automatic fallback to a paid provider if local inference is unavailable.
