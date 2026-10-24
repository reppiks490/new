"""QA35: offline owner-PC readiness; no owner media, network or cloud."""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import shutil

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'cinematic_local_render_readiness_qa35.py'
spec = importlib.util.spec_from_file_location('cinematic_qa35', SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


@pytest.fixture
def private_workspace(tmp_path):
    path = tmp_path / 'private-studio'
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path


def fake_tools(monkeypatch, *, encoder=True, ffprobe=True):
    monkeypatch.setattr(module.shutil, 'which', lambda name: f'/synthetic/bin/{name}'
                        if name != 'ffprobe' or ffprobe else None)
    def run(command, **kwargs):
        output = ' V..... libx264 H.264 encoder\n' if encoder and '-encoders' in command else ''
        return SimpleNamespace(returncode=0, stdout=output, stderr='')
    monkeypatch.setattr(module, '_invoke', run)
    monkeypatch.setattr(module.shutil, 'disk_usage', lambda path: SimpleNamespace(free=40 * 1024**3))


def test_mocked_tools_and_private_workspace_pass(monkeypatch, private_workspace):
    fake_tools(monkeypatch)
    report = module.inspect_local_readiness(private_workspace)
    assert report['local_preflight_passed']
    assert all(value['passed'] for value in report['checks'].values())
    assert str(private_workspace) not in json.dumps(report)


def test_missing_ffprobe_fails_closed(monkeypatch, private_workspace):
    fake_tools(monkeypatch, ffprobe=False)
    report = module.inspect_local_readiness(private_workspace)
    assert not report['local_preflight_passed']
    assert report['checks']['ffprobe_available']['code'] == 'ffprobe_missing_or_unusable'


def test_missing_h264_encoder_fails_closed(monkeypatch, private_workspace):
    fake_tools(monkeypatch, encoder=False)
    report = module.inspect_local_readiness(private_workspace)
    assert not report['local_preflight_passed']
    assert report['checks']['h264_encoder_available']['code'] == 'libx264_missing_or_unusable'


def test_disk_policy_is_explicit_not_a_film_size_estimate(monkeypatch, private_workspace):
    fake_tools(monkeypatch)
    monkeypatch.setattr(module.shutil, 'disk_usage', lambda path: SimpleNamespace(free=2 * 1024**3))
    assert not module.inspect_local_readiness(private_workspace)['checks']['disk_headroom_policy']['passed']
    assert module.inspect_local_readiness(private_workspace, min_free_bytes=1024)['checks']['disk_headroom_policy']['passed']


def test_missing_workspace_is_not_created(monkeypatch, tmp_path):
    fake_tools(monkeypatch)
    path = tmp_path / 'does-not-exist'
    report = module.inspect_local_readiness(path)
    assert not path.exists()
    assert not report['local_preflight_passed']


def test_symlink_workspace_is_rejected(monkeypatch, private_workspace, tmp_path):
    fake_tools(monkeypatch)
    alias = tmp_path / 'alias'
    try:
        alias.symlink_to(private_workspace, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip('symlinks unavailable')
    assert not module.inspect_local_readiness(alias)['checks']['workspace_directory']['passed']


@pytest.mark.skipif(os.name != 'posix', reason='POSIX modes')
def test_world_readable_workspace_fails_privacy(monkeypatch, private_workspace):
    fake_tools(monkeypatch)
    private_workspace.chmod(0o755)
    report = module.inspect_local_readiness(private_workspace)
    assert not report['checks']['workspace_private_posix']['passed']


def test_no_secret_path_in_cli_output(monkeypatch, private_workspace, capsys):
    fake_tools(monkeypatch)
    result = module.main(['--workspace', str(private_workspace), '--minimum-free-gib', '1'])
    assert result == 0
    output = capsys.readouterr().out
    assert str(private_workspace) not in output
    assert json.loads(output)['local_preflight_passed']


def test_bad_threshold_rejected(private_workspace):
    with pytest.raises(SystemExit):
        module.main(['--workspace', str(private_workspace), '--minimum-free-gib', 'nan'])


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'),
                    reason='local FFmpeg/FFprobe unavailable')
def test_real_synthetic_ffmpeg_encode_probe_full_decode():
    assert module._synthetic_smoke(shutil.which('ffmpeg'), shutil.which('ffprobe'))
