"""QA94: guard 600-second real-media CI against host FFmpeg apt stalls.

Static workflow contract only: this does NOT substitute for executing FFmpeg
or the application-level 600-second acceptance.
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/cinematic-600s-synthetic-media-qa93.yml"
DOCKERFILE = ROOT / ".github/qa/Dockerfile.cinematic-600s"


def test_600s_media_gate_uses_isolated_ffmpeg_container_not_host_apt():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "sudo apt-get" not in text, "Host apt mirrors previously stalled and cancelled QA93"
    assert "docker build" in text
    assert ".github/qa/Dockerfile.cinematic-600s" in text
    assert "docker run --rm --network none --read-only" in text
    assert "--env CINEMATIC_LONGFORM_MEDIA_QA=1" in text
    assert "tests/test_cinematic_600s_synthetic_media_qa93.py" in text
    assert "-m pytest" in text


def test_600s_container_installs_ffmpeg_and_runs_nonroot():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "FROM python:3.12-slim" in text
    assert "apt-get install -y --no-install-recommends ffmpeg" in text
    assert "USER 10001:10001" in text
