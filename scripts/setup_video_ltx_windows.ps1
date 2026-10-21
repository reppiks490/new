param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")),
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$LtxRevision = "e98f6d927d83c92ef2be6aec76c8440b19306e39"
$ModelRevision = "49b093a39c19169a8a81721dcc541e07e945232f"
$LtxRoot = Join-Path $RepoRoot "vendor/LTX-2"
$ModelRoot = Join-Path $RepoRoot "weights/video/ltx-2.5"

Write-Host "== Private Video Studio / LTX-2.5 setup =="
Write-Host "Checking NVIDIA driver / VRAM..."
& nvidia-smi
if ($LASTEXITCODE -ne 0) { throw "nvidia-smi failed. Install/repair the NVIDIA driver first." }

Write-Host "Checking FFmpeg..."
& ffmpeg -version | Select-Object -First 1
if ($LASTEXITCODE -ne 0) { throw "ffmpeg is required and was not found on PATH." }

New-Item -ItemType Directory -Force -Path (Join-Path $RepoRoot "vendor") | Out-Null
if (-not (Test-Path $LtxRoot)) {
    git clone https://github.com/Lightricks/LTX-2.git $LtxRoot
}
Push-Location $LtxRoot
try {
    git fetch --tags --force
    git checkout $LtxRevision
    & $Python -m pip install -U uv
    & uv sync --extra natten --frozen
    if ($LASTEXITCODE -ne 0) { throw "Pinned LTX environment setup failed." }
    & ./.venv/Scripts/python.exe -c "import importlib.metadata as m, torch; import ltx_pipelines; assert m.version('ltx-pipelines') == '1.5.0'; assert torch.cuda.is_available(); print('LTX runtime OK')"
} finally {
    Pop-Location
}

New-Item -ItemType Directory -Force -Path $ModelRoot | Out-Null
Write-Host "The LTX-2.5 repository is gated. If needed, run: hf auth login"
Write-Host "Downloading the exact pinned model revision..."
& hf download Lightricks/LTX-2.5 `
    --revision $ModelRevision `
    diffusion_models/ltx-2.5-22b-distilled-transformer-bf16.safetensors `
    text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors `
    vae/ltx-2.5-video-vae-conv-bf16.safetensors `
    vae/ltx-2.5-audio-vae-bf16.safetensors `
    latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors `
    --local-dir $ModelRoot
if ($LASTEXITCODE -ne 0) { throw "Pinned LTX-2.5 weight download failed. Accept the model license and run hf auth login." }

$LtxPython = (Resolve-Path (Join-Path $LtxRoot ".venv/Scripts/python.exe")).Path
$ResolvedModelRoot = (Resolve-Path $ModelRoot).Path
Write-Host ""
Write-Host "Setup completed. Put these values in your private .env file:"
Write-Host "CHARACTER3D_VIDEO_ENABLED=1"
Write-Host "CHARACTER3D_LTX_PYTHON=$LtxPython"
Write-Host "CHARACTER3D_LTX_MODEL_DIR=$ResolvedModelRoot"
Write-Host "CHARACTER3D_LTX_OFFLOAD=disk"
Write-Host "CHARACTER3D_LTX_TIMEOUT_SECONDS=3600"
Write-Host ""
Write-Host "Do not commit .env, weights/, workspace/, or vendor/LTX-2/."
