"""Mocked-tool contract for offline master verifier; not real FFmpeg acceptance."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from scripts import cinematic_master_acceptance as verifier


def _expected(path: Path) -> dict:
    return {
        'path': path,
        'expected_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'fps': 24, 'frames': 48, 'width': 854, 'height': 480,
    }


def _probe(*, codec='h264', frames='48', duration='2.000') -> str:
    return json.dumps({
        'streams': [{
            'codec_type': 'video', 'codec_name': codec, 'width': 854,
            'height': 480, 'avg_frame_rate': '24/1', 'nb_frames': frames,
        }],
        'format': {'duration': duration},
    })


def test_matching_bytes_probe_and_strict_decode_are_required(monkeypatch, tmp_path):
    path = tmp_path / 'private-test.mp4'
    path.write_bytes(b'synthetic placeholder - NOT A REAL MP4')
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        assert kwargs['capture_output'] and kwargs['text'] and not kwargs['check']
        if cmd[0] == 'ffprobe':
            return subprocess.CompletedProcess(cmd, 0, _probe(), '')
        return subprocess.CompletedProcess(cmd, 0, '', '')

    monkeypatch.setattr(verifier.subprocess, 'run', fake_run)
    result = verifier.verify_master(**_expected(path))
    assert result['verified'] and result['full_decode_verified']
    assert not result['actual_model_inference_verified']
    assert not result['owner_mobile_playback_verified']
    assert len(calls) == 2
    assert calls[1][1:7] == ['-nostdin', '-v', 'error', '-xerror', '-err_detect', 'explode']
    assert calls[1][-3:] == ['-f', 'null', '-']
    assert str(path) not in json.dumps(result)


def test_sha_mismatch_fails_before_probe_or_decode(monkeypatch, tmp_path):
    path = tmp_path / 'private.mp4'
    path.write_bytes(b'original')
    expected = _expected(path)
    path.write_bytes(b'mutated')
    monkeypatch.setattr(verifier.subprocess, 'run', lambda *a, **k: pytest.fail('tool invoked'))
    with pytest.raises(verifier.VerificationFailure, match='hash_mismatch'):
        verifier.verify_master(**expected)


@pytest.mark.parametrize('probe_json,reason', [
    (_probe(codec='hevc'), 'metadata_mismatch'),
    (_probe(frames='47'), 'metadata_mismatch'),
    (_probe(duration='2.2'), 'metadata_mismatch'),
    ('{"streams":[],"format":{}}', 'probe_invalid'),
])
def test_probe_mismatch_fails_before_decode(monkeypatch, tmp_path, probe_json, reason):
    path = tmp_path / 'clip.mp4'
    path.write_bytes(b'placeholder')
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, probe_json, '')

    monkeypatch.setattr(verifier.subprocess, 'run', fake_run)
    with pytest.raises(verifier.VerificationFailure, match=reason):
        verifier.verify_master(**_expected(path))
    assert len(calls) == 1


def test_decode_failure_is_not_reported_as_ready(monkeypatch, tmp_path):
    path = tmp_path / 'clip.mp4'
    path.write_bytes(b'placeholder')
    monkeypatch.setattr(verifier.subprocess, 'run', lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 0 if cmd[0] == 'ffprobe' else 1,
        _probe() if cmd[0] == 'ffprobe' else '', 'PRIVATE_INTERNAL_PATH',
    ))
    with pytest.raises(verifier.VerificationFailure, match='decode_failed'):
        verifier.verify_master(**_expected(path))


def test_overlong_master_is_rejected_before_touching_media(monkeypatch, tmp_path):
    monkeypatch.setattr(verifier.subprocess, 'run', lambda *a, **k: pytest.fail('tool invoked'))
    with pytest.raises(verifier.VerificationFailure, match='invalid_expectations'):
        verifier.verify_master(
            tmp_path / 'nonexistent.mp4', expected_sha256='0' * 64,
            fps=120, frames=72001, width=3840, height=2160,
        )


def test_cli_never_prints_private_path_or_subprocess_diagnostics(monkeypatch, tmp_path, capsys):
    path = tmp_path / 'PRIVATE_OWNER_FOOTAGE_NAME.mp4'
    path.write_bytes(b'placeholder')
    monkeypatch.setattr(verifier.subprocess, 'run', lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 1, '', 'PRIVATE_CREDENTIAL_PATH',
    ))
    args = [
        '--mp4', str(path), '--expected-sha256', hashlib.sha256(path.read_bytes()).hexdigest(),
        '--fps', '24', '--frames', '48', '--width', '854', '--height', '480',
    ]
    assert verifier.main(args) == 2
    output = capsys.readouterr().out
    assert json.loads(output) == {'verified': False, 'reason': 'probe_failed'}
    assert 'PRIVATE_' not in output
