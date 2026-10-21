# Private Local Video Studio — LTX-2.5 Setup

The Video Studio runs image-to-video inference on the owner's PC. The iPhone is only the private browser/controller. Generation has **no per-generation API call, credit charge, or cloud fallback**.

## Pinned production runtime

This integration intentionally keeps the large CUDA stack outside the FastAPI environment.

- LTX source: `Lightricks/LTX-2`
- LTX release: `v1.5.0`
- Source commit: `e98f6d927d83c92ef2be6aec76c8440b19306e39`
- Model repository: `Lightricks/LTX-2.5`
- Model revision: `49b093a39c19169a8a81721dcc541e07e945232f`
- Pipeline: `ltx_pipelines.distilled`
- Runtime FPS exposed by the current adapter: 24
- Conservative local VRAM floor: 15 GiB
- High-quality/1080 tier: approximately 31 GiB VRAM plus the diffusion video VAE

The model repository is gated. Accept its LTX-2.x license on Hugging Face before downloading. A Hugging Face **read token may be required once to download the gated weights**. The token is not required for normal generation after the files are local. The adapter starts inference with Hugging Face/Transformers offline mode and strips token/key/secret/password environment variables from the child generation process.

## 1. Check the NVIDIA GPU

On the Windows PC, run:

```bash
nvidia-smi
```

Record the GPU name and total VRAM. The server will also probe this automatically. If the PC is below the conservative 15 GiB floor, the production engine remains unavailable instead of silently switching to a paid service.

## 2. Install the pinned LTX runtime

From Git Bash in the `new` repository:

```bash
mkdir -p vendor
git clone https://github.com/Lightricks/LTX-2.git vendor/LTX-2
cd vendor/LTX-2
git checkout e98f6d927d83c92ef2be6aec76c8440b19306e39
```

Install `uv` if needed, then create the LTX environment from the pinned repository lockfile:

```bash
python -m pip install -U uv
uv sync --frozen --extra natten
```

The official project makes the `natten` acceleration optional on Windows and falls back to supported alternatives when it is unavailable.

Verify the exact package release and CUDA visibility:

```bash
./.venv/Scripts/python.exe -c "import importlib.metadata as m, torch; import ltx_pipelines; print(m.version('ltx-pipelines')); print(torch.cuda.is_available())"
```

Expected package version: `1.5.0`. CUDA should print `True`.

Return to the application repository root:

```bash
cd ../..
```

## 3. Download only the required LTX-2.5 files

Install or update the Hugging Face CLI if needed:

```bash
python -m pip install -U huggingface_hub
hf auth login
```

After accepting the model license, download the exact pinned model revision:

```bash
hf download Lightricks/LTX-2.5 \
  --revision 49b093a39c19169a8a81721dcc541e07e945232f \
  diffusion_models/ltx-2.5-22b-distilled-transformer-bf16.safetensors \
  text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors \
  vae/ltx-2.5-video-vae-conv-bf16.safetensors \
  vae/ltx-2.5-audio-vae-bf16.safetensors \
  latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors \
  --local-dir weights/video/ltx-2.5
```

The baseline pack is large (roughly 66 GiB in the official quick-start documentation). `weights/` is git-ignored and must remain outside source control.

For the high-quality profile, also download the diffusion video VAE from the same pinned revision:

```bash
hf download Lightricks/LTX-2.5 \
  --revision 49b093a39c19169a8a81721dcc541e07e945232f \
  vae/ltx-2.5-video-vae-bf16.safetensors \
  --local-dir weights/video/ltx-2.5
```

Once these downloads are complete, generation itself does not need Hugging Face authentication or Internet access.

## 4. Configure the application

Copy `.env.example` to `.env` and set the local paths. Example for Git Bash / Windows:

```env
CHARACTER3D_VIDEO_ENABLED=1
CHARACTER3D_VIDEO_MODEL_DIR=./weights/video
CHARACTER3D_LTX_PYTHON=C:/path/to/new/vendor/LTX-2/.venv/Scripts/python.exe
CHARACTER3D_LTX_MODEL_DIR=C:/path/to/new/weights/video/ltx-2.5
CHARACTER3D_LTX_OFFLOAD=disk
CHARACTER3D_LTX_QUANTIZATION=
CHARACTER3D_LTX_TIMEOUT_SECONDS=3600
```

Optional quantization values are `fp8-cast` and `fp8-scaled-mm`. Do not enable one until the target GPU is verified to support the chosen path.

`.env`, model weights, the nested LTX checkout, and generated workspace assets are git-ignored. Do not commit credentials or generated private media to this public repository.

## 5. Verify the app-side runtime

Start the private studio normally, then query:

```bash
curl -H "Authorization: Bearer $CHARACTER3D_STUDIO_TOKEN" http://127.0.0.1:8000/api/video/capabilities
```

The response should report an `ltx25_local` engine. `available` becomes `true` only when all of these are true:

- NVIDIA GPU is detected;
- VRAM meets the conservative tier;
- FFmpeg is installed;
- the pinned LTX Python environment reports `ltx-pipelines==1.5.0` and CUDA access;
- required local checkpoint files exist.

There is intentionally no cloud fallback when any item is missing.

## 6. iPhone access

Use the existing private/Tailscale path to the FastAPI studio. Keep a studio access token configured for remote API use and use HTTPS on the Tailnet. The Video panel keeps that token in the current browser tab's memory instead of persistent browser storage.

Privacy Mode is enabled by default for shoulder-surfing protection: source/result media are blurred, prompt text is masked, press-and-hold reveals temporarily, visibility/idle events conceal content, and Quick Hide replaces the video UI with a neutral workspace.

## Production notes

The current adapter uses the official distilled two-stage CLI and explicit image conditioning at frame 0 with strength `0.8`. Output dimensions are snapped to supported multiples of 64. Frames are snapped to the model temporal grid (`8k + 1`). Heavy inference is serialized by the existing one-worker GPU queue to avoid loading multiple 22B jobs concurrently.
