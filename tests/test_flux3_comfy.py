from __future__ import annotations

import json
from pathlib import Path
import subprocess

from PIL import Image

from app.image.models import ImageEditRequest

VALID_ID = "0123456789abcdef0123456789abcdef"


def _request():
    return ImageEditRequest(image_id=VALID_ID, prompt="make the jacket red", seed=22)


def _minimal_workflow():
    return {
        "nodes": [
            {"id": 1, "type": "UNETLoader", "widgets_values": ["flux3-image-klein-int8-convrot.safetensors", "default"], "widgets_values_named": {"unet_name": "flux3-image-klein-int8-convrot.safetensors", "weight_dtype": "default"}},
            {"id": 2, "type": "CLIPLoader", "widgets_values": ["qwen3vl_4b_int8_convrot.safetensors", "flux3", "default"], "widgets_values_named": {"clip_name": "qwen3vl_4b_int8_convrot.safetensors", "type": "flux3", "device": "default"}},
            {"id": 3, "type": "VAELoader", "widgets_values": ["flux2-vae.safetensors"], "widgets_values_named": {"vae_name": "flux2-vae.safetensors"}},
            {"id": 7, "type": "KSampler", "widgets_values": [123, "randomize", 16, 1, "euler", "simple", 1], "widgets_values_named": {"seed": 123, "control_after_generate": "randomize"}},
            {"id": 9, "type": "SaveImage", "widgets_values": ["sample"], "widgets_values_named": {"filename_prefix": "sample"}},
            {"id": 11, "type": "LoadImage", "widgets_values": ["sample.png", "image"], "widgets_values_named": {"image": "sample.png", "upload": "image"}},
            {"id": 33, "type": "CreateBoundingBoxes", "widgets_values": [1360, 752, [{"x": 1}], [{"id": 1}]], "widgets_values_named": {"width": 1360, "height": 752, "editor_state": [{"x": 1}], "last_incoming": [{"id": 1}]}},
            {"id": 46, "type": "CLIPLoader", "widgets_values": ["qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors", "flux3", "default"], "widgets_values_named": {"clip_name": "qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors", "type": "flux3", "device": "default"}},
            {"id": 49, "type": "Flux3LayoutPrompt", "widgets_values": ["sample prompt"], "widgets_values_named": {"prompt": "sample prompt"}},
        ],
        "links": [],
    }


def _prepare_comfy(tmp_path: Path, *, current_name: bool = False):
    home = tmp_path / "ComfyUI"
    for relative in [
        "input",
        "output",
        "models/diffusion_models",
        "models/text_encoders",
        "models/vae",
    ]:
        (home / relative).mkdir(parents=True, exist_ok=True)
    diffusion = (
        "models/diffusion_models/flux3_image_klein_sd_int8_convrot.safetensors"
        if current_name
        else "models/diffusion_models/flux3-image-klein-int8-convrot.safetensors"
    )
    for relative in [
        diffusion,
        "models/text_encoders/qwen3vl_4b_int8_convrot.safetensors",
        "models/text_encoders/qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors",
        "models/vae/flux2-vae.safetensors",
    ]:
        (home / relative).write_bytes(b"fixture")
    workflow = tmp_path / "workflow.json"
    workflow.write_text(json.dumps(_minimal_workflow()), encoding="utf-8")
    return home, workflow, Path(diffusion).name


def test_comfy_adapter_pins_official_low_vram_contract():
    from app.image.adapters import flux3_comfy as module

    assert module.COMFY_WORKFLOW_REVISION == "9afccb38bb9173575411189a75f4fc6cc8acd06c"
    assert module.COMFY_DIFFUSION_MODEL_CANDIDATES == (
        "models/diffusion_models/flux3_image_klein_sd_int8_convrot.safetensors",
        "models/diffusion_models/flux3-image-klein-int8-convrot.safetensors",
    )
    assert module.COMFY_REQUIRED_MODEL_FILES == (
        "models/text_encoders/qwen3vl_4b_int8_convrot.safetensors",
        "models/text_encoders/qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors",
        "models/vae/flux2-vae.safetensors",
    )


def test_resolve_model_files_accepts_current_and_legacy_distilled_names(tmp_path):
    from app.image.adapters.flux3_comfy import resolve_model_files

    current_home, _, current_name = _prepare_comfy(tmp_path / "current", current_name=True)
    legacy_home, _, legacy_name = _prepare_comfy(tmp_path / "legacy", current_name=False)

    assert resolve_model_files(current_home)["diffusion"] == current_name
    assert resolve_model_files(legacy_home)["diffusion"] == legacy_name


def test_patch_workflow_sets_private_inputs_models_prompt_seed_and_clears_sample_boxes():
    from app.image.adapters.flux3_comfy import patch_workflow

    patched = patch_workflow(
        _minimal_workflow(),
        source_name="private-source.png",
        prompt="change only the jacket",
        seed=77,
        output_prefix="private_result",
        model_files={
            "diffusion": "flux3_image_klein_sd_int8_convrot.safetensors",
            "text_encoder": "qwen3vl_4b_int8_convrot.safetensors",
            "prompt_upsampler": "qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors",
            "vae": "flux2-vae.safetensors",
        },
    )
    by_id = {node["id"]: node for node in patched["nodes"]}

    assert by_id[1]["widgets_values"][0] == "flux3_image_klein_sd_int8_convrot.safetensors"
    assert by_id[1]["widgets_values_named"]["unet_name"] == "flux3_image_klein_sd_int8_convrot.safetensors"
    assert by_id[2]["widgets_values"][0] == "qwen3vl_4b_int8_convrot.safetensors"
    assert by_id[46]["widgets_values"][0] == "qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors"
    assert by_id[3]["widgets_values"][0] == "flux2-vae.safetensors"
    assert by_id[11]["widgets_values"][0] == "private-source.png"
    assert by_id[11]["widgets_values_named"]["image"] == "private-source.png"
    assert by_id[49]["widgets_values"][0] == "change only the jacket"
    assert by_id[49]["widgets_values_named"]["prompt"] == "change only the jacket"
    assert by_id[7]["widgets_values"][:2] == [77, "fixed"]
    assert by_id[7]["widgets_values_named"]["seed"] == 77
    assert by_id[7]["widgets_values_named"]["control_after_generate"] == "fixed"
    assert by_id[33]["widgets_values"][2:] == [[], []]
    assert by_id[33]["widgets_values_named"]["editor_state"] == []
    assert by_id[33]["widgets_values_named"]["last_incoming"] == []
    assert by_id[9]["widgets_values"][0] == "private_result"


def test_comfy_generate_runs_local_only_patches_current_model_name_and_cleans_private_artifacts(tmp_path, monkeypatch):
    from app.image.adapters import flux3_comfy as module

    home, workflow, diffusion_name = _prepare_comfy(tmp_path, current_name=True)
    source = tmp_path / "source.png"
    output = tmp_path / "final.png"
    Image.new("RGB", (48, 32), (20, 30, 40)).save(source)

    monkeypatch.setattr(module, "detect_nvidia_gpu", lambda: {"name": "NVIDIA GeForce RTX 4060 Laptop GPU", "total_mb": 8188, "free_mb": 7600})
    monkeypatch.setattr(module, "probe_comfy_server", lambda host, port: module.ComfyProbe(True, "ready"))
    monkeypatch.setattr(module.shutil, "which", lambda executable: "C:/tools/comfy.exe" if executable == "comfy" else None)
    monkeypatch.setenv("HF_TOKEN", "must-not-leak")
    monkeypatch.setenv("TRIPO_API_KEY", "also-secret")
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        runtime_workflow = Path(command[command.index("--workflow") + 1])
        captured["runtime_workflow"] = json.loads(runtime_workflow.read_text(encoding="utf-8"))
        comfy_source = next((home / "input").glob("private-source-*.png"))
        assert comfy_source.is_file()
        generated = home / "output" / "private_result_00001_.png"
        Image.new("RGB", (48, 32), (80, 90, 100)).save(generated)
        state_file = tmp_path / "comfy-state.json"
        state_file.write_text('{"private":"state"}', encoding="utf-8")
        envelope = {
            "schema": "envelope/1",
            "type": "envelope",
            "ok": True,
            "command": "run",
            "where": "local",
            "data": {
                "status": "completed",
                "outputs": [str(generated)],
                "state_file": str(state_file),
            },
            "error": None,
        }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(envelope) + "\n", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    engine = module.Flux3KleinComfyEngine(comfy_home=home, workflow_path=workflow, comfy_executable="comfy")
    progress = []
    result = engine.generate(
        request=_request(),
        source_path=source,
        output_path=output,
        progress=lambda stage, value: progress.append((stage, value)),
    )

    assert result == output
    assert output.is_file()
    with Image.open(output) as image:
        assert image.format == "PNG"
    patched_nodes = {node["id"]: node for node in captured["runtime_workflow"]["nodes"]}
    assert patched_nodes[1]["widgets_values"][0] == diffusion_name
    command = captured["command"]
    assert "--where" in command and command[command.index("--where") + 1] == "local"
    assert "--wait" in command
    assert "--allow-spend" not in command
    assert "cloud" not in command
    assert captured["kwargs"]["shell"] is False
    env = captured["kwargs"]["env"]
    assert "HF_TOKEN" not in env
    assert "TRIPO_API_KEY" not in env
    assert not list((home / "input").glob("private-source-*.png"))
    assert not list((home / "output").glob("private_result_*.png"))
    assert not (tmp_path / "comfy-state.json").exists()
    assert progress[0][0] == "generating"
    assert progress[-1][0] == "encoding"
