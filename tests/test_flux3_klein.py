from __future__ import annotations

import importlib
from pathlib import Path
import subprocess

from PIL import Image

from app.image.models import ImageEditRequest

VALID_ID = "0123456789abcdef0123456789abcdef"
SOURCE_REVISION = "bfc8889a4497f846416f253a3972a1941ac698b9"


def _request():
    return ImageEditRequest(image_id=VALID_ID, prompt="make the jacket red", seed=22)


def _prepare_repo(tmp_path: Path):
    repo = tmp_path / "flux"
    weights = repo / "weights"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "cli.py").write_text("print('stub')", encoding="utf-8")
    (weights / "flux-3-image-klein").mkdir(parents=True)
    (weights / "pup").mkdir(parents=True)
    return repo, weights


def test_flux3_adapter_pins_reference_source_commit():
    module = importlib.import_module("app.image.adapters.flux3_klein")
    assert module.FLUX3_SOURCE_REVISION == SOURCE_REVISION
    assert module.FLUX3_MODEL_ID == "black-forest-labs/flux-3-image-klein"
    assert module.FLUX3_PUP_ID == "black-forest-labs/flux-3-image-klein-pup"


def test_flux3_build_command_uses_reference_image_prompt_seed_and_local_output(tmp_path, monkeypatch):
    module = importlib.import_module("app.image.adapters.flux3_klein")
    repo, weights = _prepare_repo(tmp_path)
    source = tmp_path / "source.png"
    output = tmp_path / "out.png"
    Image.new("RGB", (64, 48), (1, 2, 3)).save(source)
    monkeypatch.setattr(module, "detect_nvidia_gpu", lambda: {"name": "NVIDIA RTX 4090", "total_mb": 32768, "free_mb": 30000})
    engine = module.Flux3KleinLocalEngine(python_executable="flux-python", repo_dir=repo, weights_dir=weights)

    command = engine.build_command(_request(), source, output)

    assert command[:2] == ["flux-python", str(repo / "scripts" / "cli.py")]
    assert command[2] == _request().prompt
    assert command[command.index("--model") + 1] == "distilled"
    assert command[command.index("--image") + 1] == str(source)
    assert command[command.index("--out") + 1] == str(output)
    assert command[command.index("--seed") + 1] == "22"
    assert "--fp8" not in command
    assert all("http://" not in value and "https://" not in value for value in command)


def test_flux3_uses_fp8_only_when_hardware_and_memory_allow(tmp_path, monkeypatch):
    module = importlib.import_module("app.image.adapters.flux3_klein")
    repo, weights = _prepare_repo(tmp_path)
    source = tmp_path / "source.png"
    Image.new("RGB", (64, 48)).save(source)
    engine = module.Flux3KleinLocalEngine(python_executable="flux-python", repo_dir=repo, weights_dir=weights)

    monkeypatch.setattr(module, "detect_nvidia_gpu", lambda: {"name": "NVIDIA RTX 4090", "total_mb": 28672, "free_mb": 27000})
    assert "--fp8" in engine.build_command(_request(), source, tmp_path / "a.png")

    monkeypatch.setattr(module, "detect_nvidia_gpu", lambda: {"name": "NVIDIA RTX 3090", "total_mb": 28672, "free_mb": 27000})
    assert engine.capabilities().available is False


def test_flux3_generation_is_offline_sanitized_and_removes_prompt_sidecar(tmp_path, monkeypatch):
    module = importlib.import_module("app.image.adapters.flux3_klein")
    repo, weights = _prepare_repo(tmp_path)
    source = tmp_path / "source.png"
    output = tmp_path / "result.png"
    Image.new("RGB", (64, 48), (2, 3, 4)).save(source)
    monkeypatch.setenv("HF_TOKEN", "must-not-leak")
    monkeypatch.setenv("TRIPO_API_KEY", "also-secret")
    monkeypatch.setattr(module, "detect_nvidia_gpu", lambda: {"name": "NVIDIA RTX 4090", "total_mb": 32768, "free_mb": 30000})
    monkeypatch.setattr(module, "probe_flux_python", lambda executable, repo_dir: module.FluxPythonProbe(True, True, "ready"))
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        Image.new("RGB", (64, 48), (8, 9, 10)).save(output)
        output.with_suffix(".json").write_text('{"prompt":"expanded sensitive prompt"}', encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="wrote", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    progress = []
    engine = module.Flux3KleinLocalEngine(python_executable="flux-python", repo_dir=repo, weights_dir=weights)
    result = engine.generate(
        request=_request(),
        source_path=source,
        output_path=output,
        progress=lambda stage, value: progress.append((stage, value)),
    )

    assert result == output
    assert output.is_file()
    assert not output.with_suffix(".json").exists()
    env = captured["kwargs"]["env"]
    assert env["HF_HUB_OFFLINE"] == "1"
    assert env["TRANSFORMERS_OFFLINE"] == "1"
    assert env["WEIGHTS_DIR"] == str(weights)
    assert "HF_TOKEN" not in env
    assert "TRIPO_API_KEY" not in env
    assert captured["kwargs"]["shell"] is False
    assert captured["kwargs"]["cwd"] == str(repo)
    assert progress[0][0] == "generating"
    assert progress[-1][0] == "encoding"
