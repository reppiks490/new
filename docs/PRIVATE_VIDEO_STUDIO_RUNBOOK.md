# Private Video Studio Runbook

This runbook operates the mobile-first private image-to-video subsystem in `app/video`. The iPhone is the controller; the Windows NVIDIA PC performs inference locally. There is **no paid-provider fallback** and no per-generation API call or credit charge.

## Verification truth

The API, queue, privacy UI, failure contracts, and deterministic local FakeVideoEngine path are covered by automated regression tests. The production LTX-2.5 adapter is pinned to LTX source revision `e98f6d927d83c92ef2be6aec76c8440b19306e39` and exact model weights, but production LTX inference has **not yet been live-verified on the target PC** because this build session does not have that PC's NVIDIA GPU, CUDA runtime, or ~66 GiB model cache. Do not treat the production profile as live-proven until the target PC completes the live check below.

## 1. One-time Windows setup

Open PowerShell in the repository and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_video_ltx_windows.ps1
```

The script checks `nvidia-smi` and FFmpeg, installs the pinned LTX runtime, and downloads the pinned LTX-2.5 balanced weight set. The model is gated, so first-time setup may require accepting the model license and running `hf auth login`. See `docs/VIDEO_LOCAL_SETUP.md` for the exact model revision and manual commands.

After setup, copy `.env.example` to `.env` and use the local paths printed by the script. At minimum configure:

```env
CHARACTER3D_STUDIO_TOKEN=<strong-random-private-token>
CHARACTER3D_STUDIO_ORIGINS=https://<your-private-tailnet-host>
CHARACTER3D_VIDEO_ENABLED=1
CHARACTER3D_LTX_PYTHON=C:/.../vendor/LTX-2/.venv/Scripts/python.exe
CHARACTER3D_LTX_MODEL_DIR=C:/.../weights/video/ltx-2.5
CHARACTER3D_LTX_OFFLOAD=disk
```

`CHARACTER3D_STUDIO_TOKEN` is required for remote API access. Do not commit `.env`. The repository ignores `.env`, `weights/`, `workspace/`, and `vendor/LTX-2/`.

## 2. Start the studio

Activate the main app environment, then start the browser studio:

```bash
uvicorn app.studio.server:app --host 0.0.0.0 --port 8000
```

Local checks:

```bash
curl http://127.0.0.1:8000/health
curl -H "Authorization: Bearer $CHARACTER3D_STUDIO_TOKEN" http://127.0.0.1:8000/api/studio/capabilities
curl -H "Authorization: Bearer $CHARACTER3D_STUDIO_TOKEN" http://127.0.0.1:8000/api/video/capabilities
```

`/api/video/capabilities` is the truth gate. Generation must remain unavailable when the GPU, VRAM, FFmpeg, pinned LTX environment, or required local weights are missing.

## 3. Restart

Stop Uvicorn with `Ctrl+C`, then run the same Uvicorn command again. On startup, unfinished video jobs are marked interrupted/failed rather than resubmitted. This prevents an invisible duplicate generation after a process restart.

## 4. Private iPhone access

Use the existing private HTTPS/Tailscale path to the PC. Do not expose port 8000 directly to the public Internet. Open the studio in Safari, select **Video**, and enter the worker token only in the current browser tab when prompted.

Expected mobile flow:

1. Pick a source image from the iPhone.
2. Confirm the source preview is blurred while Privacy Mode is active.
3. Enter the motion prompt; it remains masked by default.
4. Select only controls advertised by `/api/video/capabilities`.
5. Generate; poll until the job reaches `Ready`.
6. Reveal the result intentionally, preview the MP4, and explicitly download/share only if desired.
7. Use **Quick Hide** to replace the workspace with the neutral view.
8. Background Safari and return; Privacy Mode must re-hide sensitive content.

Privacy Mode is shoulder-surfing protection, not anti-forensics. Someone with the unlocked device, OS/admin credentials, Tailnet ownership, or filesystem access can potentially inspect local data.

## 5. Live production verification on the target PC

After setup, verify:

```bash
nvidia-smi
ffmpeg -version
```

Start the studio and confirm `ltx25_local` reports `available: true` in `/api/video/capabilities`. Then generate one short 24-fps image-to-video clip through the real Video UI. Record the actual GPU name, total/free VRAM, chosen profile, raster, duration, generation time, and resulting MP4 size. Production LTX should not be called live-verified until that succeeds on the target PC.

## 6. Failure-mode checklist

These are expected safe failures:

- **Missing model weights** — capabilities report the missing local model components; no remote generation is attempted.
- **insufficient VRAM** — the production engine remains unavailable instead of starting an unsafe profile.
- **Missing FFmpeg** — readiness is blocked with an FFmpeg requirement.
- **Worker restart** — active jobs become interrupted/failed and are not automatically resubmitted.
- **Malformed upload** — unsupported/corrupt/oversized images return a validation error and are not persisted as usable source assets.
- **Unsupported controls** — capability-incompatible motion, FPS, resolution, or profile values are rejected.
- **Wrong bearer token** — protected `/api/*` routes return authorization failure.
- **Missing remote token** — remote API access is rejected; localhost remains available for setup.

Errors must not contain provider keys, Hugging Face tokens, the studio token, or sensitive workspace paths. The LTX child process is forced into Hugging Face/Transformers offline mode and receives a sanitized environment.

## 7. Regression commands

```bash
pytest -q
node --test tests/test_video_privacy.mjs
```

For the focused video subsystem:

```bash
python -m pytest tests/test_video_storage.py tests/test_video_runtime.py tests/test_video_api.py tests/test_video_engine.py tests/test_video_jobs.py tests/test_video_ltx25.py tests/test_video_repo_hygiene.py tests/test_video_setup_docs.py tests/test_video_runbook.py -q
```

A passing automated suite proves the app-side contracts; it does not replace the target-PC live LTX check.
