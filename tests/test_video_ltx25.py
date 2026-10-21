from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from app.video.models import VideoGenerationRequest

VALID_ID = "0123456789abcdef0123456789abcdef"
PINNED_REVISION = "e98f6d927d83c92ef2be6aec76c8440b19306e39"


def _request(**changes):
    data = {
        "image_id": VALID_ID,
        "prompt": "slow cinematic motion",
        "engine_profile": "balanced",
        "seed": 99,
        "duration_seconds": 5,
        "fps": 24,
        "resolution": "720p",
    }
    data.update(changes)
    return VideoGenerationRequest(**data)


def _make_model_pack(root: Path):
    from app.video.adapters.ltx25 import LTX25_REQUIRED_FILES

    for relative in LTX25_REQUIRED_FILES.values():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"weights")


def test_ltx25_source_revision_is_pinned():
    from app.video.adapters import ltx25

    assert ltx25.LTX2_SOURCE_REVISION == PINNED_REVISION
    assert ltx25.LTX2_RELEASE == "1.5.0"


def test_ltx25_required_split_weight_layout_matches_official_pack(tmp_path):
    from app.video.adapters.ltx25 import Ltx25Paths, LTX25_REQUIRED_FILES

    assert LTX25_REQUIRED_FILES == {
        "transformer": "diffusion_models/ltx-2.5-22b-distilled-transformer-bf16.safetensors",
        "text_encoder": "text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors",
        "video_vae": "vae/ltx-2.5-video-vae-conv-bf16.safetensors",
        "audio_vae": "vae/ltx-2.5-audio-vae-bf16.safetensors",
        "spatial_upsampler": "latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors",
    }
    paths = Ltx25Paths.from_model_dir(tmp_path)
    assert paths.missing() == [Path(value).name for value in LTX25_REQUIRED_FILES.values()]
    _make_model_pack(tmp_path)
    assert paths.missing() == []


@pytest.mark.parametrize(
    ("duration", "fps", "expected"),
    [(1, 24, 25), (2, 24, 49), (5, 24, 121), (5, 30, 153)],
)
def test_ltx25_frame_count_snaps_to_temporal_grid(duration, fps, expected):
    from app.video.adapters.ltx25 import snap_ltx_frames

    frames = snap_ltx_frames(duration, fps)
    assert frames == expected
    assert frames % 8 == 1


def test_ltx25_resolution_mapping_is_divisible_by_32_and_tracks_orientation(tmp_path):
    from app.video.adapters.ltx25 import ltx_dimensions

    landscape = tmp_path / "landscape.png"
    portrait = tmp_path / "portrait.png"
    Image.new("RGB", (1600, 900)).save(landscape)
    Image.new("RGB", (900, 1600)).save(portrait)

    assert ltx_dimensions("480p", landscape) == (832, 480)
    assert ltx_dimensions("720p", landscape) == (1280, 704)
    assert ltx_dimensions("1080p", landscape) == (1920, 1088)
    assert ltx_dimensions("720p", portrait) == (704, 1280)
    for preset in ("480p", "720p", "1080p"):
        width, height = ltx_dimensions(preset, landscape)
        assert width % 32 == 0
        assert height % 32 == 0


def test_ltx25_capabilities_require_separate_cuda_runtime_weights_and_conservative_vram(monkeypatch, tmp_path):
    from app.video.adapters import ltx25

    _make_model_pack(tmp_path)
    monkeypatch.setenv("CHARACTER3D_LTX_MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(
        ltx25,
        "probe_ltx_python",
        lambda executable: ltx25.LtxPythonProbe(True, "1.5.0", True, "ready"),
    )
    monkeypatch.setattr(ltx25, "detect_nvidia_gpu", lambda: {"name": "RTX", "total_mb": 15360, "free_mb": 14000})

    capabilities = ltx25.Ltx25LocalEngine().capabilities()

    assert capabilities.available is True
    assert capabilities.profiles == ["balanced"]
    assert capabilities.supported_resolutions == ["480p", "720p"]
    assert capabilities.supported_fps == [24]
    assert capabilities.supports_motion_strength is False
    assert capabilities.camera_motion_presets == []

    hq_path = tmp_path / ltx25.LTX25_HIGH_QUALITY_FILES["video_vae"]
    hq_path.parent.mkdir(parents=True, exist_ok=True)
    hq_path.write_bytes(b"hq weights")
    monkeypatch.setattr(ltx25, "detect_nvidia_gpu", lambda: {"name": "RTX", "total_mb": 31744, "free_mb": 30000})
    high = ltx25.Ltx25LocalEngine().capabilities()
    assert high.profiles == ["balanced", "high_quality"]
    assert high.supported_resolutions == ["480p", "720p", "1080p"]


def test_ltx25_capabilities_are_unavailable_without_complete_setup(monkeypatch, tmp_path):
    from app.video.adapters import ltx25

    monkeypatch.setenv("CHARACTER3D_LTX_MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(
        ltx25,
        "probe_ltx_python",
        lambda executable: ltx25.LtxPythonProbe(False, None, False, "ltx-pipelines unavailable"),
    )
    monkeypatch.setattr(ltx25, "detect_nvidia_gpu", lambda: None)

    capabilities = ltx25.Ltx25LocalEngine().capabilities()

    assert capabilities.available is False
    assert "ltx-pipelines unavailable" in capabilities.detail
    assert "missing model components" in capabilities.detail.lower()
    assert str(tmp_path) not in capabilities.detail


def test_ltx25_build_command_uses_local_split_paths_seed_image_and_safe_grid(monkeypatch, tmp_path):
    from app.video.adapters import ltx25

    model_dir = tmp_path / "models"
    _make_model_pack(model_dir)
    source = tmp_path / "source.png"
    output = tmp_path / "result.mp4"
    Image.new("RGB", (1600, 900)).save(source)
    monkeypatch.setenv("CHARACTER3D_LTX_MODEL_DIR", str(model_dir))
    monkeypatch.setenv("CHARACTER3D_LTX_PYTHON", "C:/ltx/.venv/Scripts/python.exe")
    monkeypatch.setenv("CHARACTER3D_LTX_OFFLOAD", "disk")
    monkeypatch.setenv("CHARACTER3D_LTX_QUANTIZATION", "")

    command = ltx25.Ltx25LocalEngine().build_command(_request(), source, output)

    assert command[:3] == ["C:/ltx/.venv/Scripts/python.exe", "-m", "ltx_pipelines.distilled"]
    assert "--transformer-path" in command
    assert str(model_dir / ltx25.LTX25_REQUIRED_FILES["transformer"]) in command
    assert command[command.index("--seed") + 1] == "99"
    assert command[command.index("--width") + 1] == "1280"
    assert command[command.index("--height") + 1] == "704"
    assert command[command.index("--num-frames") + 1] == "121"
    assert command[command.index("--frame-rate") + 1] == "24"
    image_index = command.index("--image")
    assert command[image_index + 1:image_index + 4] == [str(source), "0", "1.0"]
    assert command[command.index("--offload") + 1] == "disk"
    assert "--quantization" not in command
    assert command[command.index("--output-path") + 1] == str(output)


def test_ltx25_generate_uses_no_shell_strips_secrets_and_returns_mp4(monkeypatch, tmp_path):
    from app.video.adapters import ltx25

    model_dir = tmp_path / "models"
    _make_model_pack(model_dir)
    source = tmp_path / "source.png"
    output = tmp_path / "result.mp4"
    Image.new("RGB", (1600, 900)).save(source)
    monkeypatch.setenv("CHARACTER3D_LTX_MODEL_DIR", str(model_dir))
    monkeypatch.setenv("CHARACTER3D_LTX_PYTHON", "python-ltx")
    monkeypatch.setenv("TRIPO_API_KEY", "must-not-leak")
    monkeypatch.setenv("HF_TOKEN", "must-not-leak-either")
    monkeypatch.setattr(
        ltx25,
        "probe_ltx_python",
        lambda executable: ltx25.LtxPythonProbe(True, "1.5.0", True, "ready"),
    )
    monkeypatch.setattr(ltx25, "detect_nvidia_gpu", lambda: {"name": "RTX", "total_mb": 16384, "free_mb": 15000})
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs
        output.write_bytes(b"\x00\x00\x00\x18ftypmp42generated")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(ltx25.subprocess, "run", fake_run)
    progress = []
    result = ltx25.Ltx25LocalEngine().generate(
        request=_request(duration_seconds=2),
        source_path=source,
        output_path=output,
        progress=lambda stage, value: progress.append((stage, value)),
    )

    assert result == output
    assert seen["kwargs"]["shell"] is False
    assert seen["kwargs"]["check"] is False
    assert seen["kwargs"]["timeout"] >= 300
    child_env = seen["kwargs"]["env"]
    assert "TRIPO_API_KEY" not in child_env
    assert "HF_TOKEN" not in child_env
    assert progress[0][0] == "generating"
    assert progress[-1][0] == "encoding"


def test_ltx25_probe_checks_pinned_release_and_cuda(monkeypatch):
    from app.video.adapters import ltx25

    def fake_run(command, **kwargs):
        assert command[1] == "-c"
        return subprocess.CompletedProcess(command, 0, stdout="1.5.0\n1\n", stderr="")

    monkeypatch.setattr(ltx25.subprocess, "run", fake_run)
    probe = ltx25.probe_ltx_python("python-ltx")
    assert probe.available is True
    assert probe.version == "1.5.0"
    assert probe.cuda_available is True


def test_builtin_registry_exposes_ltx_without_importing_torch_into_server(monkeypatch, tmp_path):
    from app.video import engine
    from app.video.adapters import ltx25

    engine._ENGINE_REGISTRY.clear()
    monkeypatch.setenv("CHARACTER3D_LTX_MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(
        ltx25,
        "probe_ltx_python",
        lambda executable: ltx25.LtxPythonProbe(False, None, False, "not installed"),
    )
    monkeypatch.setattr(ltx25, "detect_nvidia_gpu", lambda: None)

    caps = engine.registered_engine_capabilities()
    names = [item.name for item in caps]
    assert "ltx25_local" in names
    assert "torch" not in engine.__dict__
