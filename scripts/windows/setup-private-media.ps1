[CmdletBinding()]
param(
    [switch]$SkipModels
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$ComfyCommit = '1a82e6d01f395b43275c77acd289af1eb7090bb9'
$WorkflowCommit = '9afccb38bb9173575411189a75f4fc6cc8acd06c'
$ComfyHome = Join-Path $RepoRoot 'vendor\ComfyUI'
$WorkflowDir = Join-Path $RepoRoot 'vendor\workflows'
$WorkflowPath = Join-Path $WorkflowDir 'image_flux3_klein_distilled_image_edit.json'
$StudioVenv = Join-Path $RepoRoot '.venv'
$ComfyVenv = Join-Path $ComfyHome '.venv'
$RequiredModelFiles = @(
    'models\diffusion_models\flux3-image-klein-int8-convrot.safetensors',
    'models\text_encoders\qwen3vl_4b_int8_convrot.safetensors',
    'models\text_encoders\qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors',
    'models\vae\flux2-vae.safetensors'
)

function Invoke-Checked {
    param(
        [Parameter(Mandatory=$true)][string]$FilePath,
        [Parameter(Mandatory=$true)][string[]]$Arguments,
        [string]$WorkingDirectory = $RepoRoot
    )
    Push-Location $WorkingDirectory
    try {
        & $FilePath @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Command failed ($LASTEXITCODE): $FilePath $($Arguments -join ' ')"
        }
    }
    finally {
        Pop-Location
    }
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw 'Git is required. Install Git for Windows, then rerun this script.'
}
if (-not (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) {
    throw 'nvidia-smi was not found. Install/repair the NVIDIA driver first.'
}

$GpuLine = (& nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits | Select-Object -First 1)
if (-not $GpuLine) { throw 'Could not read NVIDIA GPU information.' }
$GpuParts = $GpuLine -split ','
$GpuName = $GpuParts[0].Trim()
$GpuMb = [int][double]$GpuParts[1].Trim()
Write-Host "GPU: $GpuName ($GpuMb MiB VRAM)"
if ($GpuMb -lt 7680) {
    throw 'This FLUX 3 Klein int8 setup requires an 8 GB-class NVIDIA GPU.'
}

$PythonExe = $null
$PythonPrefix = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3.12 -c "import sys; print(sys.version)" *> $null
    if ($LASTEXITCODE -eq 0) {
        $PythonExe = (Get-Command py).Source
        $PythonPrefix = @('-3.12')
    }
}
if (-not $PythonExe -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $PythonExe = (Get-Command python).Source
    & $PythonExe -c "import sys; assert sys.version_info >= (3,11), sys.version" *> $null
    if ($LASTEXITCODE -ne 0) { $PythonExe = $null }
}
if (-not $PythonExe) {
    throw 'Python 3.12 is recommended and Python 3.11+ is required. Install Python, then rerun.'
}

function Invoke-BasePython {
    param([string[]]$Arguments)
    Invoke-Checked -FilePath $PythonExe -Arguments ($PythonPrefix + $Arguments)
}

if (-not (Test-Path (Join-Path $StudioVenv 'Scripts\python.exe'))) {
    Write-Host 'Creating Forma Python environment...'
    Invoke-BasePython -Arguments @('-m','venv',$StudioVenv)
}
$StudioPython = Join-Path $StudioVenv 'Scripts\python.exe'
Invoke-Checked -FilePath $StudioPython -Arguments @('-m','pip','install','--upgrade','pip','setuptools','wheel')
Invoke-Checked -FilePath $StudioPython -Arguments @('-m','pip','install','-e','.') -WorkingDirectory $RepoRoot

if (-not (Test-Path (Join-Path $ComfyHome '.git'))) {
    Write-Host 'Cloning pinned ComfyUI runtime...'
    New-Item -ItemType Directory -Force -Path (Split-Path $ComfyHome -Parent) | Out-Null
    Invoke-Checked -FilePath 'git' -Arguments @('clone','https://github.com/Comfy-Org/ComfyUI.git',$ComfyHome)
}
Write-Host "Pinning ComfyUI to $ComfyCommit..."
Invoke-Checked -FilePath 'git' -Arguments @('-C',$ComfyHome,'fetch','origin',$ComfyCommit)
Invoke-Checked -FilePath 'git' -Arguments @('-C',$ComfyHome,'checkout','--detach',$ComfyCommit)

if (-not (Test-Path (Join-Path $ComfyVenv 'Scripts\python.exe'))) {
    Write-Host 'Creating ComfyUI Python environment...'
    Invoke-BasePython -Arguments @('-m','venv',$ComfyVenv)
}
$ComfyPython = Join-Path $ComfyVenv 'Scripts\python.exe'
Invoke-Checked -FilePath $ComfyPython -Arguments @('-m','pip','install','--upgrade','pip','setuptools','wheel')
Write-Host 'Installing stable NVIDIA PyTorch (CUDA 13.0)...'
Invoke-Checked -FilePath $ComfyPython -Arguments @('-m','pip','install','torch','torchvision','torchaudio','--extra-index-url','https://download.pytorch.org/whl/cu130')
Invoke-Checked -FilePath $ComfyPython -Arguments @('-m','pip','install','-r','requirements.txt') -WorkingDirectory $ComfyHome
Invoke-Checked -FilePath $ComfyPython -Arguments @('-m','pip','install','comfy-cli','huggingface_hub')

New-Item -ItemType Directory -Force -Path $WorkflowDir | Out-Null
$WorkflowUrl = "https://raw.githubusercontent.com/Comfy-Org/workflow_templates/$WorkflowCommit/templates/image_flux3_klein_distilled_image_edit.json"
Write-Host 'Downloading pinned official FLUX 3 Klein int8 edit workflow...'
Invoke-WebRequest -UseBasicParsing -Uri $WorkflowUrl -OutFile $WorkflowPath

if (-not $SkipModels) {
    $HfExe = Join-Path $ComfyVenv 'Scripts\hf.exe'
    if (-not (Test-Path $HfExe)) { throw 'Hugging Face CLI was not installed correctly.' }
    & $HfExe auth whoami *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host ''
        Write-Host 'FLUX 3 Image Klein files are gated by the model license.' -ForegroundColor Yellow
        Write-Host 'Accept the black-forest-labs/flux-3-image-klein-comfy terms in your browser, then run:' -ForegroundColor Yellow
        Write-Host "  & `"$HfExe`" auth login" -ForegroundColor Cyan
        throw 'Hugging Face authentication is required once for model download. Runtime generation remains local.'
    }

    Write-Host 'Downloading the four official 8 GB int8 model files...'
    Invoke-Checked -FilePath $HfExe -Arguments @(
        'download','black-forest-labs/flux-3-image-klein-comfy',
        'diffusion_models/flux3-image-klein-int8-convrot.safetensors',
        'text_encoders/qwen3vl_4b_int8_convrot.safetensors',
        'text_encoders/qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors',
        'vae/flux2-vae.safetensors',
        '--local-dir',(Join-Path $ComfyHome 'models')
    )
}

$Missing = @()
foreach ($Relative in $RequiredModelFiles) {
    if (-not (Test-Path (Join-Path $ComfyHome $Relative))) { $Missing += $Relative }
}
if (-not $SkipModels -and $Missing.Count -gt 0) {
    throw "Setup finished with missing model files: $($Missing -join ', ')"
}

Write-Host ''
Write-Host 'Private media runtime setup complete.' -ForegroundColor Green
Write-Host "ComfyUI: $ComfyHome"
Write-Host "Workflow: $WorkflowPath"
Write-Host 'Next: run scripts\windows\start-private-media.ps1'
