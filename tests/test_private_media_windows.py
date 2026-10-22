from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "scripts" / "windows" / "setup-private-media.ps1"
START = ROOT / "scripts" / "windows" / "start-private-media.ps1"


def test_windows_setup_is_pinned_and_targets_8gb_flux_int8_path():
    text = SETUP.read_text(encoding="utf-8")
    assert "1a82e6d01f395b43275c77acd289af1eb7090bb9" in text
    assert "9afccb38bb9173575411189a75f4fc6cc8acd06c" in text
    assert "if ($GpuMb -lt 7680)" in text
    assert "flux3_image_klein_sd_int8_convrot.safetensors" in text
    assert "flux3-image-klein-int8-convrot.safetensors" in text
    assert "qwen3vl_4b_int8_convrot.safetensors" in text
    assert "qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors" in text
    assert "flux2-vae.safetensors" in text
    assert "--extra-index-url','https://download.pytorch.org/whl/cu130" in text


def test_windows_setup_falls_back_between_checkpoint_names_without_hiding_progress():
    text = SETUP.read_text(encoding="utf-8")
    assert "foreach ($Candidate in $DiffusionModelCandidates)" in text
    assert "| Out-Host" in text
    assert "$ExitCode = $LASTEXITCODE" in text
    assert "Test-AnyDiffusionModel" in text


def test_windows_launcher_binds_inference_and_studio_to_loopback_and_uses_legacy_safe_rng():
    text = START.read_text(encoding="utf-8")
    assert "'main.py','--listen','127.0.0.1','--port','8188'" in text
    assert "'--host','127.0.0.1','--port','8000'" in text
    assert "RandomNumberGenerator]::Create()" in text
    assert "RandomNumberGenerator]::Fill" not in text
    assert "tailscale serve --bg http://127.0.0.1:8000" in text
