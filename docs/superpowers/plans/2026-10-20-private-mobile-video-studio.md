# Private Mobile Video Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a private, iPhone-first image-to-video studio to `reppiks490/new` that runs generation locally on the owner's PC, returns MP4 output, requires no metered inference API, and includes shoulder-surfing privacy controls.

**Architecture:** Add an isolated `app/video` subsystem mounted into the existing FastAPI studio. Reuse the current authenticated API middleware, workspace persistence, job model, and static web shell; keep 3D generation untouched. Introduce a local-engine adapter boundary, hardware capability detection, a deterministic fake engine for tests, then one production local image-to-video adapter chosen by detected GPU/VRAM.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, SQLite, Pillow, PyTorch/CUDA when available, FFmpeg, browser JavaScript/CSS, pytest, Node-based `.mjs` tests already used by the repo.

**Spec:** `docs/superpowers/specs/2026-10-20-private-mobile-video-studio-design.md`

## Global Constraints

- No per-generation API credits, inference tokens, paid provider fallback, or required cloud generation service.
- iPhone is the client/controller; local PC performs heavy inference.
- Existing 3D studio routes and GLB workflows must remain functional.
- Remote `/api/*` access remains protected by the existing `CHARACTER3D_STUDIO_TOKEN` middleware.
- Generated media stays local unless explicitly downloaded/exported.
- Privacy Mode defaults to masking prompts and blurring media, supports Quick Hide, and re-hides on background/resume.
- Never persist or return secret credential values in errors or capability responses.
- Production engine must be locally runnable and selected from real hardware capability; no silent fallback to a paid provider.
- Adult-content handling must not enable sexual depictions of minors or non-consensual sexual deepfakes of real people.

## Review Focus

1. **Insufficient GPU/VRAM:** the API must return an actionable unavailable capability instead of crashing or invoking a paid service; covered in Task 2 capability tests and Task 6 adapter selection tests.
2. **Malformed/oversized source media:** invalid image bytes, unsupported formats, and excessive dimensions must fail with 4xx responses and never reach inference; covered in Task 3 upload tests.
3. **Interrupted generation:** server restart during `loading/generating/encoding` must mark the video job interrupted and never auto-resubmit; covered in Task 4 job lifecycle tests.
4. **Privacy-state leakage:** backgrounding, pointer release, Quick Hide, or switching views must re-mask prompt/media; covered in Task 5 browser-state tests.
5. **Unsupported adapter controls:** parameters such as motion strength or camera presets must be rejected/disabled when the selected engine does not support them; covered in Task 4 API validation and Task 6 adapter-capability tests.

---

## File Structure

**Create**
- `app/video/__init__.py` — package marker.
- `app/video/models.py` — API/domain Pydantic models and engine capability types.
- `app/video/runtime.py` — CUDA/GPU/VRAM/FFmpeg/model readiness detection.
- `app/video/storage.py` — video asset paths and video-specific record helpers built on existing workspace conventions.
- `app/video/engine.py` — engine protocol, registry, fake engine, engine selection.
- `app/video/jobs.py` — background worker orchestration and video job lifecycle.
- `app/video/router.py` — `/api/video/*` routes.
- `app/video/adapters/ltx.py` or the final selected local adapter module — production local I2V adapter.
- `app/studio/web/video-studio.js` — Video panel rendering, upload/generate/poll/preview/gallery logic.
- `app/studio/web/privacy-mode.js` — isolated privacy state machine and DOM masking helpers.
- `tests/test_video_runtime.py`
- `tests/test_video_storage.py`
- `tests/test_video_api.py`
- `tests/test_video_jobs.py`
- `tests/test_video_engine.py`
- `tests/test_video_privacy.mjs`

**Modify**
- `app/studio/server.py` — mount video router; interrupt video jobs during lifespan.
- `app/studio/storage.py` — broaden shared safe asset extensions only if required by the chosen reuse path; preserve traversal/symlink protections.
- `app/studio/web/index.html` — add Video navigation entry and module script if needed.
- `app/studio/web/app.js` — add a narrow handoff to the video module; do not absorb video implementation into this already-large file.
- `app/studio/web/style.css` — mobile video/privacy states and responsive layout.
- `.env.example` — document video configuration knobs.
- `pyproject.toml` — add only dependencies needed by the verified production adapter/runtime.

---

### Task 1: Video Domain Models and Safe Storage

**Files:**
- Create: `app/video/__init__.py`
- Create: `app/video/models.py`
- Create: `app/video/storage.py`
- Test: `tests/test_video_storage.py`

**Interfaces:**
- Produces: `VideoGenerationRequest`, `PrivacyPreferences`, `EngineCapabilities`, `VideoRuntimeReport`, `video_asset_path(identifier: str, extension: str) -> Path`, `put_video_record(...)`, `get_video_record(...)`, `list_video_records(...)`.

- [ ] **Step 1: Write failing storage/model tests**
  - Assert 32-hex IDs are accepted for `png`, `mp4`, and internal `json` metadata.
  - Assert path traversal, invalid IDs, unsupported extensions, and symlink escape are rejected.
  - Assert generation-request bounds reject empty prompt, invalid FPS, unsupported duration/resolution, and malformed image IDs.
  - Assert privacy defaults are `privacy_mode=True`, `mask_prompts=True`, `blur_media=True`, `quick_hide=True`, `idle_lock_seconds=30`, `require_unlock_on_resume=True`, `neutral_project_names=True`.

- [ ] **Step 2: Run tests and verify failure**
  - Run: `pytest tests/test_video_storage.py -v`
  - Expected: FAIL because `app.video` modules do not exist.

- [ ] **Step 3: Implement the minimal domain/storage layer**
  - `VideoGenerationRequest` must include `image_id`, `prompt`, `engine_profile`, `seed`, `duration_seconds`, `fps`, `resolution`, optional `motion_strength`, optional `camera_motion`.
  - `video_asset_path` must use `workspace/studio/video-assets` by default and never derive paths from user filenames.
  - Persist video records through SQLite-compatible helpers with kinds `video_job`, `video_privacy`, and `video_asset_meta`.

- [ ] **Step 4: Run tests and verify pass**
  - Run: `pytest tests/test_video_storage.py -v`
  - Expected: PASS.

- [ ] **Step 5: Commit**
  - `git commit -m "feat(video): add domain models and safe storage"`

### Task 2: Hardware and Runtime Capability Detection

**Files:**
- Create: `app/video/runtime.py`
- Test: `tests/test_video_runtime.py`
- Modify: `.env.example`

**Interfaces:**
- Consumes: `VideoRuntimeReport`, `EngineCapabilities` from Task 1.
- Produces: `detect_video_runtime() -> VideoRuntimeReport`, `detect_nvidia_gpu()`, `ffmpeg_available()`, `recommended_profile(report) -> str | None`.

- [ ] **Step 1: Write failing capability tests**
  - Mock no CUDA: report is available=false with a clear blocker and no cloud fallback.
  - Mock CUDA GPU + VRAM: report exposes GPU name and total/free VRAM but no secrets.
  - Mock missing FFmpeg: generation readiness is false with encoding blocker.
  - Assert profile recommendation maps low/balanced/high-quality using constants defined in the module rather than guessed at request time.

- [ ] **Step 2: Run tests and verify failure**
  - Run: `pytest tests/test_video_runtime.py -v`
  - Expected: FAIL because runtime detector does not exist.

- [ ] **Step 3: Implement detection**
  - Use `torch.cuda.is_available()` when torch is installed; tolerate torch absent without preventing the studio from booting.
  - Use safe subprocess inspection (`nvidia-smi` and `ffmpeg -version`) with short timeouts and no shell interpolation.
  - Return structured blockers instead of raising for absent hardware.

- [ ] **Step 4: Update `.env.example`**
  - Add the non-secret variables from the approved spec: `CHARACTER3D_VIDEO_ENABLED`, `CHARACTER3D_VIDEO_MODEL_DIR`, `CHARACTER3D_VIDEO_PRIVACY_DEFAULT`, `CHARACTER3D_VIDEO_IDLE_LOCK_SECONDS`, `CHARACTER3D_VIDEO_QUICK_HIDE_ENABLED`, `CHARACTER3D_VIDEO_REQUIRE_UNLOCK_ON_RESUME`.

- [ ] **Step 5: Run tests**
  - Run: `pytest tests/test_video_runtime.py -v`
  - Expected: PASS.

- [ ] **Step 6: Commit**
  - `git commit -m "feat(video): detect local GPU and encoding readiness"`

### Task 3: Authenticated Video API and Image Ingest

**Files:**
- Create: `app/video/router.py`
- Create: `tests/test_video_api.py`
- Modify: `app/studio/server.py`

**Interfaces:**
- Consumes: storage and runtime interfaces from Tasks 1-2.
- Produces: `router = APIRouter(prefix="/api/video", ...)` with `/capabilities`, `/images`, `/jobs`, `/jobs/{id}`, `/assets/{filename}`, `/privacy` GET/PUT endpoints; `POST /generate` is wired to Task 4 worker.

- [ ] **Step 1: Write failing API tests**
  - `/api/video/capabilities` returns structured local readiness.
  - image upload accepts PNG/JPEG/WebP, normalizes to RGB PNG, rejects >12 MiB and >20 MP.
  - remote-style request without configured bearer token is rejected by existing middleware behavior; authenticated request succeeds.
  - MP4 asset response uses `video/mp4`.
  - privacy GET/PUT returns only validated settings.
  - existing `/api/studio/capabilities` remains reachable.

- [ ] **Step 2: Run focused tests and verify failure**
  - Run: `pytest tests/test_video_api.py -v`
  - Expected: FAIL because router is not mounted.

- [ ] **Step 3: Implement router and mount it**
  - Reuse the existing server middleware; do not introduce a second bearer-token mechanism.
  - Use the same image validation rules as the current studio route, factored only if duplication becomes unsafe.
  - Serve only validated video asset IDs/extensions.

- [ ] **Step 4: Run tests**
  - Run: `pytest tests/test_video_api.py -v`
  - Expected: PASS.

- [ ] **Step 5: Commit**
  - `git commit -m "feat(video): add authenticated video API"`

### Task 4: Background Jobs and Engine Contract

**Files:**
- Create: `app/video/engine.py`
- Create: `app/video/jobs.py`
- Create: `tests/test_video_engine.py`
- Create: `tests/test_video_jobs.py`
- Modify: `app/video/router.py`
- Modify: `app/studio/server.py`

**Interfaces:**
- Produces: `ImageToVideoEngine` protocol, `register_engine(...)`, `select_engine(...)`, deterministic `FakeVideoEngine`, `enqueue_video_job(req)`, `execute_video_job(job_id, req)`, `interrupt_active_video_jobs()`.

- [ ] **Step 1: Write failing engine/job tests**
  - fake engine deterministically emits a tiny valid test MP4 fixture or an FFmpeg-produced short clip without network access.
  - unsupported controls are rejected against engine capabilities.
  - lifecycle is `queued -> loading -> generating -> encoding -> succeeded`.
  - exceptions persist sanitized failure text.
  - restart marks active jobs `failed/Interrupted` and does not resubmit.
  - no engine available yields 503/actionable blocker; no paid provider is invoked.

- [ ] **Step 2: Run tests and verify failure**
  - Run: `pytest tests/test_video_engine.py tests/test_video_jobs.py -v`

- [ ] **Step 3: Implement protocol, registry, fake engine, worker**
  - Heavy engines must be lazy-loaded; nothing large loads on import.
  - Use a dedicated single-worker executor for GPU generation initially to prevent simultaneous model copies exhausting VRAM.
  - Persist progress coarsely; never expose raw model filesystem paths in public job payloads.

- [ ] **Step 4: Wire `POST /api/video/generate` to the worker**
  - Validate source asset before queueing.
  - Validate requested controls against selected engine capabilities.
  - Return immediately with persisted queued job.

- [ ] **Step 5: Run tests**
  - Run: `pytest tests/test_video_engine.py tests/test_video_jobs.py tests/test_video_api.py -v`
  - Expected: PASS.

- [ ] **Step 6: Commit**
  - `git commit -m "feat(video): add local generation job engine"`

### Task 5: Mobile Video Studio and Shoulder-Surfing Privacy Mode

**Files:**
- Create: `app/studio/web/video-studio.js`
- Create: `app/studio/web/privacy-mode.js`
- Create: `tests/test_video_privacy.mjs`
- Modify: `app/studio/web/index.html`
- Modify: `app/studio/web/app.js`
- Modify: `app/studio/web/style.css`

**Interfaces:**
- Consumes: `/api/video/*` endpoints from Tasks 3-4.
- Produces: `createPrivacyController(...)`, `renderVideoStudio(...)`, `pollVideoJob(...)`, `quickHide()`, `revealWhileHeld(...)`.

- [ ] **Step 1: Write failing browser-state tests**
  - default privacy masks prompt and applies media blur.
  - pointer/touch down reveals; `pointerup`, `pointercancel`, and `touchend` re-hide.
  - `visibilitychange` to hidden immediately re-hides content.
  - Quick Hide replaces sensitive video/prompt UI with a neutral workspace state.
  - privacy-active job cards use neutral `Project N` labels and omit raw prompts.
  - unsupported engine controls render disabled or hidden based on capability payload.

- [ ] **Step 2: Run JS tests and verify failure**
  - Run using the repo's existing Node `.mjs` test convention, e.g. `node --test tests/test_video_privacy.mjs`.

- [ ] **Step 3: Implement isolated privacy controller**
  - No persistent storage of studio bearer token.
  - Session PIN may gate reveal state; do not claim native Face ID unless WebAuthn is separately implemented and tested.

- [ ] **Step 4: Implement mobile Video panel**
  - Add Video navigation entry.
  - iPhone portrait layout: upload, masked preview, prompt, supported generation controls, generate, progress, preview, explicit download, recent gallery.
  - Do not auto-save to Photos/iCloud.

- [ ] **Step 5: Run tests and regression smoke tests**
  - Run: `node --test tests/test_video_privacy.mjs`
  - Run: `pytest tests/test_video_api.py -v`
  - Expected: PASS.

- [ ] **Step 6: Commit**
  - `git commit -m "feat(video): add mobile studio privacy mode"`

### Task 6: Production Local I2V Adapter

**Files:**
- Create: `app/video/adapters/__init__.py`
- Create: `app/video/adapters/<selected_engine>.py`
- Modify: `app/video/engine.py`
- Modify: `app/video/runtime.py`
- Modify: `pyproject.toml`
- Test: `tests/test_video_engine.py`

**Interfaces:**
- Consumes: runtime report and `ImageToVideoEngine` protocol.
- Produces: one production adapter implementing local image-to-video generation with no metered API calls.

- [ ] **Step 1: Detect target hardware on the owner's PC**
  - Run `nvidia-smi` and record GPU model, total VRAM, driver, CUDA compatibility.
  - If NVIDIA is absent, inspect alternative supported local acceleration only if a verified adapter exists; otherwise report the local-hardware blocker.

- [ ] **Step 2: Select the strongest practical local engine**
  - Evaluate current verified open-weight options (LTX-family, Wan-family, or another maintained local I2V implementation) against actual VRAM, license, model size, supported resolution/duration, and dependency stability.
  - Pin the exact model/revision and implementation dependency; do not track an unpinned moving Git branch in production once a working revision is verified.

- [ ] **Step 3: Write adapter contract tests**
  - lazy initialization;
  - source image conversion and parameter mapping;
  - supported-control enforcement;
  - deterministic seed forwarding;
  - no HTTP call to a paid inference endpoint;
  - output path exists and is MP4 after encoding.

- [ ] **Step 4: Implement the selected adapter**
  - Load weights lazily in bf16/fp16/quantized form appropriate to hardware.
  - Use CPU offload/tiling only when supported and necessary.
  - Emit progress callbacks around load, inference, decode, and encoding stages.

- [ ] **Step 5: Pin dependencies and document model setup**
  - Add only required Python dependencies to `pyproject.toml`.
  - Document weight download/cache procedure without committing model weights.

- [ ] **Step 6: Run adapter tests**
  - Unit tests must pass without GPU by mocking the backend.
  - On target PC, run one live end-to-end image-to-video generation and record the verified profile.

- [ ] **Step 7: Commit**
  - `git commit -m "feat(video): add verified local image-to-video adapter"`

### Task 7: End-to-End Verification and Regression Gate

**Files:**
- Modify tests only if verification uncovers a missing regression assertion.
- Modify `README.md` or `GUIDE.md` with operator steps after behavior is verified.

**Interfaces:**
- Consumes: complete subsystem.
- Produces: verified startup/use instructions and evidence that the original 3D studio still works.

- [ ] **Step 1: Run Python test suite**
  - Run: `pytest -q`
  - Expected: PASS, excluding only already-documented environment-dependent live tests.

- [ ] **Step 2: Run JS tests**
  - Run existing `.mjs` tests plus `node --test tests/test_video_privacy.mjs`.
  - Expected: PASS.

- [ ] **Step 3: Start the studio locally**
  - Run: `uvicorn app.studio.server:app --host 0.0.0.0 --port 8000`
  - Verify `/health`, `/api/studio/capabilities`, `/api/video/capabilities`, upload, generation, polling, MP4 serving.

- [ ] **Step 4: Verify iPhone private-access flow**
  - Open via the existing private HTTPS/Tailscale path.
  - Confirm auth, image picker, generation, MP4 preview/download, Privacy Mode, Quick Hide, and background re-hide.

- [ ] **Step 5: Verify failure modes**
  - Missing model weights, insufficient VRAM, missing FFmpeg, worker restart, malformed upload, unsupported controls, wrong bearer token.
  - Each must produce an actionable error without secret leakage and without paid fallback.

- [ ] **Step 6: Document exact operator commands**
  - Add setup/start/restart commands and model cache requirements to the repo docs.

- [ ] **Step 7: Final commit**
  - `git commit -m "docs(video): add verified private studio runbook"`
