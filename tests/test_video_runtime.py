from __future__ import annotations

import importlib
import subprocess


def runtime():
    return importlib.import_module("app.video.runtime")


def test_detect_nvidia_gpu_parses_name_and_memory(monkeypatch):
    module = runtime()

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="NVIDIA GeForce RTX 4090, 24564, 20310\n",
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module.detect_nvidia_gpu() == {
        "name": "NVIDIA GeForce RTX 4090",
        "total_mb": 24564,
        "free_mb": 20310,
    }


def test_detect_video_runtime_reports_no_cuda_without_cloud_fallback(monkeypatch):
    module = runtime()
    monkeypatch.setattr(
        module,
        "detect_nvidia_gpu",
        lambda: {"name": "NVIDIA RTX", "total_mb": 24576, "free_mb": 20000},
    )
    monkeypatch.setattr(module, "_torch_cuda_available", lambda: False)
    monkeypatch.setattr(module, "ffmpeg_available", lambda: True)

    report = module.detect_video_runtime()

    assert report.available is False
    assert report.cuda_available is False
    assert any("CUDA" in blocker for blocker in report.blockers)
    assert any("paid-provider fallback" in note for note in report.notes)


def test_detect_video_runtime_exposes_gpu_memory_without_secrets(monkeypatch):
    module = runtime()
    monkeypatch.setenv("TRIPO_API_KEY", "super-secret-value")
    monkeypatch.setenv("LTX_API_KEY", "another-secret")
    monkeypatch.setattr(
        module,
        "detect_nvidia_gpu",
        lambda: {"name": "NVIDIA GeForce RTX 4090", "total_mb": 24576, "free_mb": 22000},
    )
    monkeypatch.setattr(module, "_torch_cuda_available", lambda: True)
    monkeypatch.setattr(module, "ffmpeg_available", lambda: True)

    report = module.detect_video_runtime()
    serialized = report.model_dump_json()

    assert report.available is True
    assert report.gpu_name == "NVIDIA GeForce RTX 4090"
    assert report.vram_total_mb == 24576
    assert report.vram_free_mb == 22000
    assert report.recommended_profile == "high_quality"
    assert "super-secret-value" not in serialized
    assert "another-secret" not in serialized


def test_missing_ffmpeg_blocks_generation_readiness(monkeypatch):
    module = runtime()
    monkeypatch.setattr(
        module,
        "detect_nvidia_gpu",
        lambda: {"name": "NVIDIA RTX", "total_mb": 16384, "free_mb": 12000},
    )
    monkeypatch.setattr(module, "_torch_cuda_available", lambda: True)
    monkeypatch.setattr(module, "ffmpeg_available", lambda: False)

    report = module.detect_video_runtime()

    assert report.available is False
    assert report.ffmpeg_available is False
    assert any("FFmpeg" in blocker for blocker in report.blockers)


def test_recommended_profile_uses_explicit_vram_thresholds():
    module = runtime()
    report_type = importlib.import_module("app.video.models").VideoRuntimeReport

    assert module.recommended_profile(report_type(cuda_available=True, ffmpeg_available=True, vram_total_mb=8191)) is None
    assert module.recommended_profile(report_type(cuda_available=True, ffmpeg_available=True, vram_total_mb=8192)) == "low_vram"
    assert module.recommended_profile(report_type(cuda_available=True, ffmpeg_available=True, vram_total_mb=16384)) == "balanced"
    assert module.recommended_profile(report_type(cuda_available=True, ffmpeg_available=True, vram_total_mb=24576)) == "high_quality"
