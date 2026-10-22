# PRIVATE MEDIA STUDIO — START HERE

> **Authoritative handoff for the private image-to-image + image-to-video build in `reppiks490/new`.**
>
> This file exists so the project can be resumed from GitHub without relying on chat history.
>
> **Repository:** `reppiks490/new`  
> **Implementation branch:** `feat/private-mobile-video-studio`  
> **Snapshot documented:** commit `99683bebd084170ffe701c8201d29ad83f9c51f6` (2026-10-22; branch may advance after this document)  
> **Existing/base branch visible in the GitHub mobile app:** `claude/effort-status-tjzcfd`

---

## 1. Mission

Build a **private, mobile-first media studio** inside the existing Character3D / Forma browser studio so the owner can use an iPhone as the controller while a Windows PC performs local GPU inference.

Required user flow:

1. Open the private studio on iPhone.
2. Upload/select an image.
3. Type an image-edit or motion prompt.
4. Generate either:
   - a new edited/generated **PNG** from the source image, or
   - a generated **MP4** from the source image.
5. Preview the private result on iPhone.
6. Download/share only when explicitly requested.

The production target is **local inference**, not paid per-generation provider calls. Gated model downloads may require one-time account/license acceptance, but normal generation must not silently fall back to cloud APIs, credits, or paid providers.

---

## 2. Architecture

```text
iPhone Safari / private web UI
        |
        |  HTTPS / Tailnet preferred
        v
FastAPI studio in reppiks490/new
        |
        +--> existing Character3D / Forma routes
        |
        +--> /api/video  -> local image-to-video queue -> LTX-2.5 adapter
        |
        +--> /api/image  -> local image-edit queue     -> FLUX 3 Image Klein adapters
        |
        +--> shared one-GPU execution lane
        |
        +--> private workspace files on the PC
```

Heavy CUDA/PyTorch/model runtimes are intentionally kept out of the normal FastAPI process where practical. Production model adapters launch dedicated local runtimes/subprocesses so the web server remains small and stable.

The PC must be powered on and reachable while the iPhone is used unless inference is later moved to another always-on machine.

---

## 3. Current server integration

`app/studio/server.py` currently includes all three families:

- existing studio router
- `app.video.router`
- `app.image.router`

Startup also interrupts unfinished 3D, video, and image jobs rather than invisibly resubmitting them after a restart.

The shared private API middleware remains the security boundary for `/api/*` routes.

### Authentication behavior

If `CHARACTER3D_STUDIO_TOKEN` is set:

- protected API requests require `Authorization: Bearer <token>`.

If no token is set:

- localhost/test clients may use the API;
- remote clients are rejected.

State-changing requests are checked against `CHARACTER3D_STUDIO_ORIGINS`.

Remote iPhone use should therefore have both:

```env
CHARACTER3D_STUDIO_TOKEN=<strong-random-token>
CHARACTER3D_STUDIO_ORIGINS=https://<private-tailnet-host>
```

Do not expose port 8000 directly to the public Internet.

---

## 4. Video subsystem — implemented

Main package:

```text
app/video/
  adapters/ltx25.py
  engine.py
  gpu_executor.py
  jobs.py
  models.py
  router.py
  runtime.py
  storage.py
```

### API surface

```text
GET  /api/video/capabilities
POST /api/video/images
POST /api/video/generate
GET  /api/video/jobs
GET  /api/video/jobs/{id}
GET  /api/video/assets/{id}.png
GET  /api/video/assets/{id}.mp4
GET  /api/video/privacy
PUT  /api/video/privacy
```

### Upload rules

Source images:

- PNG, JPEG, or WebP
- maximum 12 MiB
- maximum 20 megapixels
- EXIF orientation corrected
- normalized to RGB PNG before inference

### Job rules

- persistent local job records
- prompt text is not returned as a normal job-list field
- unfinished jobs become interrupted/failed on application restart
- one GPU generation worker prevents simultaneous giant model loads
- no automatic cloud fallback

### Private media responses

Private PNG/MP4 responses use `Cache-Control: no-store`.

The browser fetches authenticated media using the bearer header and creates an in-tab blob/object URL. The studio token is **not** placed into query strings or media URLs.

---

## 5. Production image-to-video engine: LTX-2.5

Production adapter:

```text
app/video/adapters/ltx25.py
```

Pinned runtime:

- source repository: `Lightricks/LTX-2`
- LTX release: `1.5.0`
- source revision: `e98f6d927d83c92ef2be6aec76c8440b19306e39`
- model repository: `Lightricks/LTX-2.5`
- model revision: `49b093a39c19169a8a81721dcc541e07e945232f`
- pipeline: `ltx_pipelines.distilled`

The adapter is deliberately conservative. It remains unavailable instead of lying when hardware/model prerequisites are missing.

Current conservative application gates:

- NVIDIA CUDA environment required
- roughly 15 GiB VRAM minimum for the balanced production profile
- roughly 31 GiB for the high-quality/1080 tier
- required local checkpoint files must exist
- configured LTX Python environment must expose `ltx-pipelines==1.5.0` and CUDA
- FFmpeg is part of overall production readiness/operation

The adapter runs model work locally and forces Hugging Face/Transformers offline mode during generation. Secret-bearing environment variables are removed from the child process.

### LTX setup docs already in this repo

Read:

```text
docs/VIDEO_LOCAL_SETUP.md
docs/PRIVATE_VIDEO_STUDIO_RUNBOOK.md
scripts/setup_video_ltx_windows.ps1
```

---

## 6. Image subsystem — implemented backend

Main package:

```text
app/image/
  adapters/
    flux3_klein.py
    flux3_comfy.py
  engine.py
  jobs.py
  models.py
  router.py
  storage.py
```

The package exists on `feat/private-mobile-video-studio` and is already wired into `app/studio/server.py`.

### API surface

```text
GET  /api/image/capabilities
POST /api/image/images
POST /api/image/generate
GET  /api/image/jobs
GET  /api/image/jobs/{id}
GET  /api/image/assets/{id}.png
```

Image uploads follow the same private-source philosophy as video: validated image formats, size/pixel limits, normalized PC-side files, authenticated result serving, and no-store caching.

Image jobs use the shared local GPU execution lane so image generation and 22B video generation do not fight for VRAM concurrently.

---

## 7. Production image engine: FLUX 3 Image Klein

Primary reference implementation:

```text
app/image/adapters/flux3_klein.py
```

Low-VRAM/alternate path:

```text
app/image/adapters/flux3_comfy.py
```

Official model capabilities researched and used by this build:

- approximately 5.6B parameters
- text-to-image
- image editing
- up to 10 reference images in the official model
- optional layout/bounding-box control in the upstream model
- distilled model uses 16 steps
- prompt upsampler is strongly recommended by Black Forest Labs

Official reference source used during implementation was inspected at source commit:

```text
bfc8889a4497f846416f253a3972a1941ac698b9
```

Relevant repositories:

```text
black-forest-labs/flux-3-image-klein
black-forest-labs/flux-3-image-klein-pup
```

FLUX 3 Image Klein weights are gated and use the FLUX Kommunity License. The prompt upsampler uses Apache 2.0.

### Memory reality

The official reference runner reports approximately:

- BF16: ~31 GB peak GPU memory
- FP8: ~26 GB peak GPU memory
- NVFP4: ~25 GB and Blackwell-specific

The official project points lower-VRAM RTX systems toward the FLUX ComfyUI quantized files, including an int8 route intended for GPUs around the RTX 3070 / 8 GB class.

**Do not choose the final FLUX production profile until the actual PC GPU/VRAM is known.**

### Privacy requirement unique to FLUX

The upstream CLI writes sidecar JSON containing prompt/seed metadata. The private adapter must remove that JSON sidecar after generation so private prompt data is not unintentionally retained next to output media.

The production adapter must also:

- run local-only
- use `shell=False`
- sanitize secrets from child environments
- force offline HF/Transformers behavior for generation
- refuse unavailable model/hardware states rather than call a cloud provider

---

## 8. Shared GPU lane

The media build uses a shared single-worker GPU executor rather than separate image and video workers competing simultaneously.

Reason: LTX-2.5 and FLUX can consume tens of gigabytes of VRAM. Parallel execution on a normal desktop GPU would create avoidable OOM failures and instability.

Expected behavior:

```text
image job ----\
               > shared GPU queue -> exactly one heavy inference task at a time
video job ----/
```

Future concurrency should only be enabled after measuring the actual GPU and proving there is safe VRAM headroom.

---

## 9. Mobile / privacy mode

The Video Studio UI already contains shoulder-surfing controls. The same privacy principles govern private image editing.

Privacy Mode requirements:

- source preview blurred by default
- generated result blurred until intentionally revealed
- prompt masked like a password/private field
- press-and-hold reveal / release to conceal
- Quick Hide replaces sensitive content with a neutral workspace
- automatically conceal when Safari/app loses focus
- neutral project/job labels
- no notification previews containing sensitive content
- no private-result thumbnails on an unlocked landing page
- private assets fetched using Authorization headers, never tokens in URLs
- object URLs revoked when the private workspace exits

This is **shoulder-surfing privacy**, not anti-forensics. It does not promise secrecy from someone with OS/admin access, an unlocked device, filesystem access, Tailnet ownership, or deliberate screen observation.

---

## 10. Repository privacy rules

This repository is currently public.

Never commit:

```text
.env
.env.*
weights/
workspace/
vendor/LTX-2/
private uploaded images
private generated images
private generated videos
Hugging Face tokens
studio bearer tokens
provider/API keys
```

`.gitignore` was extended to protect the main local model/runtime/media paths.

If the code itself is intended to remain private, change repository visibility separately; do not rely on `.gitignore` for source-code secrecy.

---

## 11. CI / automated verification

GitHub Actions workflow:

```text
.github/workflows/ci.yml
```

The media branch CI includes:

- Python 3.11 tests
- Python 3.12 tests with warning enforcement
- Node 22 browser/privacy tests
- Docker smoke verification

Earlier video-only branch state was fully green.

At the time this document was written, the latest image-extension run for commit `99683bebd084170ffe701c8201d29ad83f9c51f6` was queued, so **do not describe the new image extension as CI-green until the latest run completes successfully**.

Useful local commands:

```bash
pytest -q
node --test tests/*.mjs
```

The automated tests prove software contracts. They do **not** prove that the owner's GPU can run the real LTX/FLUX checkpoints.

---

## 12. Current physical-PC status / known blocker

On 2026-10-22 the owner ran the following from Git Bash:

```bash
nvidia-smi
ffmpeg -version
```

Both returned `command not found`.

This does **not** prove there is no NVIDIA GPU or no FFmpeg installation; Git Bash may simply not see them. It means production hardware readiness is currently unverified.

### Next hardware discovery commands — run in Windows PowerShell

```powershell
Get-CimInstance Win32_VideoController | Select-Object Name, DriverVersion, AdapterRAM
where.exe nvidia-smi
where.exe ffmpeg
Test-Path "C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"
```

If the last command returns `True`:

```powershell
& "C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"
```

If FFmpeg is absent, an intended installation route is:

```powershell
winget install Gyan.FFmpeg
```

Then close/reopen the terminal and verify:

```powershell
ffmpeg -version
```

**Do not install or choose a heavyweight FLUX/LTX profile until the GPU name and actual dedicated VRAM are known.**

---

## 13. Recommended Git commands on the owner's PC

The implementation is on the feature branch, not the older branch shown by default in the GitHub mobile app.

From the repository clone:

```bash
git fetch --all --prune
git checkout feat/private-mobile-video-studio
git pull --ff-only origin feat/private-mobile-video-studio
git status
git log -5 --oneline
```

If the repository has not been cloned yet:

```bash
git clone https://github.com/reppiks490/new.git
cd new
git checkout feat/private-mobile-video-studio
```

Do not force-reset a working directory that contains local/private files without inspecting `git status` first.

---

## 14. Local server launch

The private browser studio entry point is:

```bash
uvicorn app.studio.server:app --host 0.0.0.0 --port 8000
```

Local health:

```bash
curl http://127.0.0.1:8000/health
```

With token configured:

```bash
curl -H "Authorization: Bearer $CHARACTER3D_STUDIO_TOKEN" http://127.0.0.1:8000/api/video/capabilities
curl -H "Authorization: Bearer $CHARACTER3D_STUDIO_TOKEN" http://127.0.0.1:8000/api/image/capabilities
```

Those capability endpoints are the runtime truth source. If an engine says unavailable, fix the stated local prerequisite rather than bypassing the gate.

---

## 15. Tailscale / iPhone target

Recommended production topology:

```text
iPhone Safari
   -> private Tailnet HTTPS hostname
   -> Windows PC
   -> FastAPI private studio
   -> local image/video models
```

Do not create a fake public URL in documentation.

A final iPhone link should only be published after:

- the PC server is actually running,
- the private/Tailnet hostname resolves,
- bearer auth works,
- source upload works from the phone,
- the phone can receive an authenticated private result.

---

## 16. What has already been verified

Verified through software tests and local smoke paths during implementation:

- FastAPI video routes mount without breaking existing studio routes
- existing bearer auth protects video/image APIs
- private upload validation
- persistent video/image job records
- restart interruption semantics
- deterministic local fake-video job -> MP4 path
- authenticated private media serving
- `Cache-Control: no-store`
- browser privacy behaviors
- bearer-authenticated media blobs without leaking token into URL
- video engine capability validation
- production LTX adapter command construction and hardware/model gates
- FLUX adapter contract and model-file drift tests are being added/expanded on the image branch

---

## 17. What is NOT yet proven

Do not claim any of the following until there is fresh evidence from the owner's Windows PC:

- real LTX-2.5 CUDA image-to-video generation succeeded
- real FLUX 3 Image Klein image editing succeeded
- exact generation speed on the owner's GPU
- exact safe VRAM profile
- FFmpeg is installed and usable
- NVIDIA runtime is visible
- the final iPhone private Tailnet URL is live

Automated CI cannot substitute for those hardware checks.

---

## 18. Definition of DONE

The build is only operationally complete when all of these pass on the owner's machine:

1. `nvidia-smi` (or equivalent GPU discovery) identifies the target GPU and VRAM.
2. FFmpeg is available where required.
3. Required gated model licenses have been accepted.
4. Model files are downloaded outside Git.
5. `/api/video/capabilities` reports a production video engine available.
6. `/api/image/capabilities` reports a production image-edit engine available.
7. A real source image is uploaded.
8. A real FLUX image edit produces a valid private PNG.
9. A real LTX image-to-video job produces a valid private MP4.
10. The same outputs are previewable from the iPhone through the authenticated private route.
11. Privacy Mode re-blurs/re-hides content on background/Quick Hide.
12. Latest CI is green.
13. No secrets/model weights/private media are present in Git history.

Until steps 8 and 9 succeed with real models, say **application/integration verified, production GPU generation not yet live-verified**.

---

## 19. Continuation priority

When another AI/engineer resumes this project, continue in this order:

1. Check latest head of `feat/private-mobile-video-studio` and latest CI.
2. Fix any red image-subsystem tests before adding features.
3. Finish image Studio mobile UI integration if any controls remain backend-only.
4. Capture the owner's PowerShell GPU output.
5. Choose FLUX reference/FP8/Comfy-int8 path based on real GPU architecture + VRAM.
6. Install/verify FFmpeg.
7. Install pinned/gated local model runtime(s).
8. Run one real FLUX image edit.
9. Run one short real LTX video generation.
10. Start private Tailnet access and verify from iPhone.
11. Only then publish the actual private working link.

Do not restart architecture research from zero. The local/private adapter design and security model are already established.

---

## 20. Existing project documents

Important media-specific files already present:

```text
docs/superpowers/specs/2026-10-20-private-mobile-video-studio-design.md
docs/superpowers/plans/2026-10-20-private-mobile-video-studio.md
docs/VIDEO_LOCAL_SETUP.md
docs/PRIVATE_VIDEO_STUDIO_RUNBOOK.md
scripts/setup_video_ltx_windows.ps1
```

General existing Character3D / Forma documentation remains in `README.md`, `GUIDE.md`, and the other `docs/` files.

---

## 21. Safety / intended use boundary

Private generation can support fictional/synthetic adult content and consensual adult material where legally permitted. The implementation must not be extended to facilitate non-consensual intimate imagery or sexual deepfakes of real people.

Privacy features are for legitimate private viewing / shoulder-surfing protection, not evidence wiping, spyware, bypassing device administration, or defeating platform controls.

---

## 22. One-line status

**Current status:** the private FastAPI image/video architecture, video UI/privacy system, LTX adapter, image backend, FLUX adapters, job/storage/auth foundations, and CI gates are substantially implemented; the remaining decisive milestone is real on-owner-PC GPU verification and then a live private iPhone route.