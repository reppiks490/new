from pathlib import Path

SOURCE_REVISION = "e98f6d927d83c92ef2be6aec76c8440b19306e39"
MODEL_REVISION = "49b093a39c19169a8a81721dcc541e07e945232f"


def test_local_video_setup_pins_runtime_and_model_download():
    root = Path(__file__).resolve().parents[1]
    text = (root / 'docs' / 'VIDEO_LOCAL_SETUP.md').read_text()
    assert SOURCE_REVISION in text
    assert MODEL_REVISION in text
    assert f'--revision {MODEL_REVISION}' in text
    assert 'CHARACTER3D_LTX_PYTHON' in text
    assert 'CHARACTER3D_LTX_MODEL_DIR' in text
    assert 'hf auth login' in text
    assert 'no per-generation' in text.lower()
