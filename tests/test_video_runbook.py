from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REV = "e98f6d927d83c92ef2be6aec76c8440b19306e39"
REQUIRED_WEIGHTS = [
    "diffusion_models/ltx-2.5-22b-distilled-transformer-bf16.safetensors",
    "text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors",
    "vae/ltx-2.5-video-vae-conv-bf16.safetensors",
    "vae/ltx-2.5-audio-vae-bf16.safetensors",
    "latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors",
]


def test_public_repo_ignores_private_runtime_and_model_files():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignored
    assert "weights/" in ignored
    assert "workspace/" in ignored


def test_windows_setup_script_pins_ltx_and_required_balanced_weights():
    script = (ROOT / "scripts" / "setup_video_ltx_windows.ps1").read_text(encoding="utf-8")
    assert REV in script
    assert "uv sync --extra natten" in script
    assert "nvidia-smi" in script
    assert "ffmpeg" in script
    assert "hf download Lightricks/LTX-2.5" in script
    for relative in REQUIRED_WEIGHTS:
        assert relative in script
    assert "CHARACTER3D_LTX_PYTHON" in script
    assert "CHARACTER3D_LTX_MODEL_DIR" in script
    assert "HF_HUB_OFFLINE" not in script  # adapter forces offline per generation; setup must still download.


def test_runbook_contains_setup_start_restart_private_mobile_and_truth_gates():
    runbook = (ROOT / "docs" / "PRIVATE_VIDEO_STUDIO_RUNBOOK.md").read_text(encoding="utf-8")
    for term in [
        REV,
        "nvidia-smi",
        "setup_video_ltx_windows.ps1",
        "CHARACTER3D_STUDIO_TOKEN",
        "CHARACTER3D_STUDIO_ORIGINS",
        "uvicorn app.studio.server:app",
        "/api/video/capabilities",
        "Tailscale",
        "Quick Hide",
        "Privacy Mode",
        "Missing model weights",
        "insufficient VRAM",
        "FFmpeg",
        "no paid-provider fallback",
    ]:
        assert term in runbook
    assert "not yet been live-verified" in runbook
    assert "target PC" in runbook


def test_guide_links_private_video_runbook():
    guide = (ROOT / "GUIDE.md").read_text(encoding="utf-8")
    assert "docs/PRIVATE_VIDEO_STUDIO_RUNBOOK.md" in guide
