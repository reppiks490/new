from __future__ import annotations

import importlib
import os
from pathlib import Path
import subprocess
import sys

import pytest
from PIL import Image

from app.video.models import VideoGenerationRequest

VALID_ID = "0123456789abcdef0123456789abcdef"
SOURCE_REVISION = "e98f6d927d83c92ef2be6aec76c8440b19306e39"
MODEL_REVISION = "49b093a39c19169a8a81721dcc541e07e945232f"


def _request(**changes):
    data = {
        "image_id": VALID_ID,
        "prompt": "subtle breathing and a slow camera push",
        "engine_profile": "balanced",
        "seed": 123,
        "duration_seconds": 2,
        "fps": 24,
        "resolution": "720p",
    }
    data.update(changes)
    return VideoGenerationRequest(**data)


def _touch_required(module, model_dir: Path, *, high_quality: bool = False):
    paths = module.Ltx25Paths.from_model_dir(model_dir)
    for relative in module.LTX25_REQUIRED_FILES.values():
        path = model_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"weight")
    if high_quality:
        for relative in module.LTX25_HIGH_QUALITY_FILES.values():
            path = model_dir / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"weight")
    return paths


def test_ltx25_adapter_pins_official_release_and_model_revision():
    module = importlib.import_module("app.video.adapters.ltx25")
    assert module.LTX2_RELEASE == "1.5.0"
    assert module.LTX2_SOURCE_REVISION == SOURCE_REVISION
    assert module.LTX25_MODEL_ID == "Lightricks/LTX-2.5"
    assert module.LTX25_MODEL_REVISION == MODEL_REVISION


def test_ltx25_module_import_does_not_import_torch_or_ltx_pipelines():
    code = (
        "import sys; import app.video.adapters.ltx25; "
        "print(int('torch' in sys.modules), int('ltx_pipelines' in sys.modules))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "0 0"


def test_ltx25_required_split_weight_layout_matches_official_pack(tmp_path):
    module = importlib.import_module("app.video.adapters.ltx25")
    assert module.LTX25_REQUIRED_FILES == {
        "transformer": "diffusion_models/ltx-2.5-22b-distilled-transformer-bf16.safetensors",
        "text_encoder": "text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors",
        "video_vae": "vae/ltx-2.5-video-vae-conv-bf16.safetensors",
        "audio_vae": "vae/ltx-2.5-audio-vae-bf16.safetensors",
        "spatial_upsampler": "latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors",
    }
    paths = module.Ltx25Paths.from_model_dir(tmp_path)
    assert paths.missing()
    _touch_required(module, tmp_path)
    assert paths.missing() == []
    assert paths.high_quality_missing()
    _touch_required(module, tmp_path, high_quality=True)
    assert paths.high_quality_missing() == []


@pytest.mark.parametrize(
    ("duration", "fps", "expected"),
    [(1, 24, 25), (2, 24, 49), (5, 24, 121), (5, 30, 153)],
)
def test_ltx25_frame_count_snaps_to_temporal_grid(duration, fps, expected):
    module = importlib.import_module("app.video.adapters.ltx25")
    frames = module.snap_ltx_frames(duration, fps)
    assert frames == expected
    assert frames % 8 == 1


def test_ltx25_resolution_mapping_is_divisible_by_64_and_tracks_orientation(tmp_path):
    module = importlib.import_module("app.video.adapters.ltx25")
    landscape = tmp_path / "landscape.png"
    portrait = tmp_path / "portrait.png"
    square = tmp_path / "square.png"
    Image.new("RGB", (1600, 900)).save(landscape)
    Image.new("RGB", (900, 1600)).save(portrait)
    Image.new("RGB", (1000, 1000)).save(square)

    assert module.ltx_dimensions("480p", landscape) == (896, 512)
    assert module.ltx_dimensions("720p", landscape) == (1280, 704)
    assert module.ltx_dimensions("1080p", landscape) == (1920, 1088)
    assert module.ltx_dimensions("720p", portrait) == (704, 1280)
    assert module.ltx_dimensions("720p", square) == (960, 960)
    for preset in ("480p", "720p", "1080p"):
        width, height = module.ltx_dimensions(preset, landscape)
        assert width % 64 == 0
        assert height % 64 == 0


def test_ltx25_capabilities_are_hardware_and_model_gated(monkeypatch, tmp_path):
    module = importlib.import_module("app.video.adapters.ltx25")
    _touch_required(module, tmp_path)
    monkeypatch.setattr(
        module,
        "probe_ltx_python",
        lambda executable: module.LtxPythonProbe(True, "1.5.0", True, "ready"),
    )
    engine = module.Ltx25LocalEngine(python_executable="python", model_dir=tmp_path)

    monkeypatch.setattr(module, "detect_nvidia_gpu", lambda: {"name": "RTX", "total_mb": 14336, "free_mb": 12000})
    low = engine.capabilities()
    assert low.available is False
    assert low.profiles == []

    monkeypatch.setattr(module, "detect_nvidia_gpu", lambda: {"name": "RTX", "total_mb": 24576, "free_mb": 20000})
    balanced = engine.capabilities()
    assert balanced.available is True
    assert balanced.profiles == ["balanced"]
    assert balanced.supported_resolutions == ["480p", "720p"]
    assert balanced.supported_fps == [24]
    assert balanced.supports_motion_strength is False
    assert balanced.camera_motion_presets == []

    _touch_required(module, tmp_path, high_quality=True)
    monkeypatch.setattr(module, "detect_nvidia_gpu", lambda: {"name": "RTX", "total_mb": 32768, "free_mb": 30000})
    high = engine.capabilities()
    assert high.available is True
    assert high.profiles == ["balanced", "high_quality"]
    assert high.supported_resolutions == ["480p", "720p", "1080p"]


def test_ltx25_capabilities_are_unavailable_without_complete_setup(monkeypatch, tmp_path):
    module = importlib.import_module("app.video.adapters.ltx25")
    monkeypatch.setattr(
        module,
        "probe_ltx_python",
        lambda executable: module.LtxPythonProbe(False, None, False, "ltx-pipelines unavailable"),
    )
    monkeypatch.setattr(module, "detect_nvidia_gpu", lambda: None)
    engine = module.Ltx25LocalEngine(python_executable="python", model_dir=tmp_path)

    capabilities = engine.capabilities()

    assert capabilities.available is False
    assert "ltx-pipelines unavailable" in capabilities.detail
    assert "missing model components" in capabilities.detail.lower()
    assert str(tmp_path) not in capabilities.detail


def test_ltx25_command_maps_local_paths_seed_prompt_image_and_safe_grid(tmp_path):
    module = importlib.import_module("app.video.adapters.ltx25")
    _touch_required(module, tmp_path)
    source = tmp_path / "portrait.png"
    Image.new("RGB", (720, 1280), (1, 2, 3)).save(source)
    output = tmp_path / "out.mp4"
    engine = module.Ltx25LocalEngine(python_executable="ltx-python", model_dir=tmp_path)

    command = engine.build_command(_request(), source, output)

    assert command[:3] == ["ltx-python", "-m", "ltx_pipelines.distilled"]
    assert str(tmp_path / module.LTX25_REQUIRED_FILES["transformer"]) in command
    assert command[command.index("--prompt") + 1] == _request().prompt
    assert command[command.index("--seed") + 1] == "123"
    assert command[command.index("--num-frames") + 1] == "49"
    assert command[command.index("--frame-rate") + 1] == "24"
    assert command[command.index("--width") + 1] == "704"
    assert command[command.index("--height") + 1] == "1280"
    image_index = command.index("--image")
    assert command[image_index + 1 : image_index + 4] == [str(source), "0", "0.8"]
    assert command[command.index("--output-path") + 1] == str(output)
    assert all("http://" not in part and "https://" not in part for part in command)


def test_ltx25_generate_uses_offline_local_subprocess_and_sanitizes_secrets(monkeypatch, tmp_path):
    module = importlib.import_module("app.video.adapters.ltx25")
    _touch_required(module, tmp_path)
    source = tmp_path / "source.png"
    Image.new("RGB", (1280, 720), (2, 3, 4)).save(source)
    output = tmp_path / "result.mp4"
    monkeypatch.setenv("HF_TOKEN", "must-not-leak")
    monkeypatch.setenv("TRIPO_API_KEY", "also-secret")
    monkeypatch.setattr(
        module,
        "probe_ltx_python",
        lambda executable: module.LtxPythonProbe(True, "1.5.0", True, "ready"),
    )
    monkeypatch.setattr(module, "detect_nvidia_gpu", lambda: {"name": "RTX", "total_mb": 24576, "free_mb": 22000})
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        output.write_bytes(b"\x00\x00\x00\x18ftypmp42local")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    progress = []
    result = module.Ltx25LocalEngine(python_executable="ltx-python", model_dir=tmp_path).generate(
        request=_request(),
        source_path=source,
        output_path=output,
        progress=lambda stage, value: progress.append((stage, value)),
    )

    assert result == output
    assert b"ftyp" in output.read_bytes()[:64]
    kwargs = captured["kwargs"]
    assert kwargs["shell"] is False
    assert kwargs["check"] is False
    assert kwargs["timeout"] >= 300
    child_env = kwargs["env"]
    assert child_env["HF_HUB_OFFLINE"] == "1"
    assert child_env["TRANSFORMERS_OFFLINE"] == "1"
    assert child_env["HF_HUB_DISABLE_TELEMETRY"] == "1"
    assert "HF_TOKEN" not in child_env
    assert "TRIPO_API_KEY" not in child_env
    assert all("http://" not in part and "https://" not in part for part in captured["command"])
    assert progress[0][0] == "generating"
    assert progress[-1][0] == "encoding"


def test_ltx25_probe_checks_pinned_release_cuda_and_uses_sanitized_env(monkeypatch):
    module = importlib.import_module("app.video.adapters.ltx25")
    monkeypatch.setenv("HF_TOKEN", "secret")
    captured = {}

    def fake_run(command, **kwargs):
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(command, 0, stdout="1.5.0\n1\n", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    probe = module.probe_ltx_python("python-ltx")
    assert probe.available is True
    assert probe.version == "1.5.0"
    assert probe.cuda_available is True
    assert "HF_TOKEN" not in captured["env"]
    assert captured["env"]["HF_HUB_OFFLINE"] == "1"


def test_builtin_registry_exposes_ltx_without_importing_torch_into_server(monkeypatch, tmp_path):
    engine = importlib.import_module("app.video.engine")
    module = importlib.import_module("app.video.adapters.ltx25")
    engine._ENGINE_REGISTRY.clear()
    monkeypatch.setattr(
        module,
        "probe_ltx_python",
        lambda executable: module.LtxPythonProbe(False, None, False, "not installed"),
    )
    monkeypatch.setattr(module, "detect_nvidia_gpu", lambda: None)
    monkeypatch.setenv("CHARACTER3D_LTX_MODEL_DIR", str(tmp_path))

    capabilities = engine.registered_engine_capabilities()

    assert any(item.name == "ltx25_local" for item in capabilities)
    assert "torch" not in engine.__dict__
