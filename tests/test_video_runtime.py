from app.video import runtime


def test_no_cuda_is_unavailable_and_never_suggests_cloud(monkeypatch):
    monkeypatch.setattr(runtime, '_torch_state', lambda: (True, False, None))
    monkeypatch.setattr(runtime, 'detect_nvidia_gpu', lambda: None)
    monkeypatch.setattr(runtime, 'ffmpeg_available', lambda: True)
    report = runtime.detect_video_runtime()
    assert report.available is False
    assert any('CUDA' in item for item in report.blockers)
    assert all('cloud' not in item.lower() and 'provider' not in item.lower() for item in report.notes + report.blockers)


def test_cuda_gpu_reports_name_and_memory_without_secrets(monkeypatch):
    monkeypatch.setattr(runtime, '_torch_state', lambda: (True, True, 'CUDA 13.0'))
    monkeypatch.setattr(runtime, 'detect_nvidia_gpu', lambda: {'name': 'RTX Test', 'total_mb': 24576, 'free_mb': 20000})
    monkeypatch.setattr(runtime, 'ffmpeg_available', lambda: True)
    report = runtime.detect_video_runtime()
    payload = report.model_dump()
    assert report.available is True
    assert report.gpu_name == 'RTX Test'
    assert report.vram_total_mb == 24576
    assert report.vram_free_mb == 20000
    assert 'API_KEY' not in repr(payload)
    assert report.recommended_profile == 'high_quality'


def test_missing_ffmpeg_blocks_generation(monkeypatch):
    monkeypatch.setattr(runtime, '_torch_state', lambda: (True, True, None))
    monkeypatch.setattr(runtime, 'detect_nvidia_gpu', lambda: {'name': 'RTX Test', 'total_mb': 16384, 'free_mb': 12000})
    monkeypatch.setattr(runtime, 'ffmpeg_available', lambda: False)
    report = runtime.detect_video_runtime()
    assert report.available is False
    assert any('FFmpeg' in item for item in report.blockers)


def test_recommended_profile_uses_declared_thresholds():
    from app.video.models import VideoRuntimeReport
    low = VideoRuntimeReport(vram_total_mb=runtime.LOW_VRAM_MIN_MB, cuda_available=True, ffmpeg_available=True)
    balanced = VideoRuntimeReport(vram_total_mb=runtime.BALANCED_VRAM_MIN_MB, cuda_available=True, ffmpeg_available=True)
    high = VideoRuntimeReport(vram_total_mb=runtime.HIGH_QUALITY_VRAM_MIN_MB, cuda_available=True, ffmpeg_available=True)
    too_small = VideoRuntimeReport(vram_total_mb=runtime.LOW_VRAM_MIN_MB - 1, cuda_available=True, ffmpeg_available=True)
    assert runtime.recommended_profile(low) == 'low_vram'
    assert runtime.recommended_profile(balanced) == 'balanced'
    assert runtime.recommended_profile(high) == 'high_quality'
    assert runtime.recommended_profile(too_small) is None
