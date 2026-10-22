[CmdletBinding()]
param(
    [switch]$TailscaleServe
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$ComfyHome = Join-Path $RepoRoot 'vendor\ComfyUI'
$ComfyPython = Join-Path $ComfyHome '.venv\Scripts\python.exe'
$ComfyCli = Join-Path $ComfyHome '.venv\Scripts\comfy.exe'
$WorkflowPath = Join-Path $RepoRoot 'vendor\workflows\image_flux3_klein_distilled_image_edit.json'
$StudioPython = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$Workspace = Join-Path $RepoRoot 'workspace\studio'
$TokenFile = Join-Path $Workspace 'access-token.txt'

foreach ($Required in @($ComfyPython,$ComfyCli,$WorkflowPath,$StudioPython)) {
    if (-not (Test-Path $Required)) {
        throw "Missing runtime file: $Required`nRun scripts\windows\setup-private-media.ps1 first."
    }
}

New-Item -ItemType Directory -Force -Path $Workspace | Out-Null
if (-not (Test-Path $TokenFile)) {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    }
    finally {
        $rng.Dispose()
    }
    $token = -join ($bytes | ForEach-Object { $_.ToString('x2') })
    Set-Content -Path $TokenFile -Value $token -NoNewline -Encoding ascii
}
$StudioToken = (Get-Content $TokenFile -Raw).Trim()
if (-not $StudioToken) { throw 'Studio token file is empty.' }

$env:CHARACTER3D_COMFY_HOME = $ComfyHome
$env:CHARACTER3D_COMFY_CLI = $ComfyCli
$env:CHARACTER3D_COMFY_WORKFLOW = $WorkflowPath
$env:CHARACTER3D_COMFY_HOST = '127.0.0.1'
$env:CHARACTER3D_COMFY_PORT = '8188'
$env:CHARACTER3D_STUDIO_WORKSPACE = $Workspace
$env:CHARACTER3D_STUDIO_TOKEN = $StudioToken

function Test-HttpReady {
    param([string]$Url)
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300)
    }
    catch { return $false }
}

$ComfyProcess = $null
$StudioProcess = $null
try {
    if (-not (Test-HttpReady 'http://127.0.0.1:8188/system_stats')) {
        Write-Host 'Starting private ComfyUI worker on 127.0.0.1:8188...'
        $ComfyProcess = Start-Process -FilePath $ComfyPython -ArgumentList @(
            'main.py','--listen','127.0.0.1','--port','8188'
        ) -WorkingDirectory $ComfyHome -PassThru
        $Ready = $false
        for ($i=0; $i -lt 120; $i++) {
            if ($ComfyProcess.HasExited) {
                throw "ComfyUI exited during startup with code $($ComfyProcess.ExitCode)."
            }
            if (Test-HttpReady 'http://127.0.0.1:8188/system_stats') { $Ready = $true; break }
            Start-Sleep -Seconds 1
        }
        if (-not $Ready) { throw 'ComfyUI did not become ready on port 8188.' }
    }
    else {
        Write-Host 'Using existing ComfyUI worker on 127.0.0.1:8188.'
    }

    Write-Host 'Starting Forma private studio on 127.0.0.1:8000...'
    $StudioProcess = Start-Process -FilePath $StudioPython -ArgumentList @(
        '-m','uvicorn','app.studio.server:app','--host','127.0.0.1','--port','8000'
    ) -WorkingDirectory $RepoRoot -PassThru

    $StudioReady = $false
    for ($i=0; $i -lt 60; $i++) {
        if ($StudioProcess.HasExited) {
            throw "Forma studio exited during startup with code $($StudioProcess.ExitCode)."
        }
        if (Test-HttpReady 'http://127.0.0.1:8000/health') { $StudioReady = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $StudioReady) { throw 'Forma studio did not become ready on port 8000.' }

    if ($TailscaleServe) {
        if (-not (Get-Command tailscale -ErrorAction SilentlyContinue)) {
            throw 'Tailscale CLI was not found. Install/sign in to Tailscale or omit -TailscaleServe.'
        }
        Write-Host 'Publishing the studio through your private Tailnet...'
        & tailscale serve --bg http://127.0.0.1:8000
        if ($LASTEXITCODE -ne 0) { throw 'tailscale serve failed.' }
    }

    Write-Host ''
    Write-Host 'Private media studio is running.' -ForegroundColor Green
    Write-Host 'Local: http://127.0.0.1:8000'
    Write-Host "Studio token: $StudioToken"
    Write-Host 'The token is stored only under workspace/studio and is ignored by Git.'
    Write-Host 'Press Ctrl+C in this PowerShell window to stop the processes started by this launcher.'

    while (-not $StudioProcess.HasExited) { Start-Sleep -Seconds 2 }
}
finally {
    if ($StudioProcess -and -not $StudioProcess.HasExited) {
        Stop-Process -Id $StudioProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($ComfyProcess -and -not $ComfyProcess.HasExited) {
        Stop-Process -Id $ComfyProcess.Id -Force -ErrorAction SilentlyContinue
    }
}
