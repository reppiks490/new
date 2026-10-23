"""QA21: real synthetic FFmpeg audio compatibility, skew and privacy acceptance."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from scripts import cinematic_mobile_audio_preflight as audio_gate
from scripts.cinematic_mobile_progressive_preflight import verify_mobile_progressive


def _tools() -> str:
    ffmpeg = shutil.which('ffmpeg')
    ffprobe = shutil.which('ffprobe')
    if ffmpeg and ffprobe:
        p = subprocess.run([ffmpeg, '-hide_banner', '-encoders'], capture_output=True,
                           text=True, check=False, timeout=20)
        if p.returncode == 0 and all(x in p.stdout for x in ('libx264', 'aac', 'alac')):
            return ffmpeg
    if os.environ.get('CINEMATIC_REQUIRE_REAL_MEDIA') == '1':
        pytest.fail('QA21 requires ffmpeg, ffprobe, libx264, AAC and ALAC encoders')
    pytest.skip('synthetic media toolchain unavailable')


def _encode(path: Path, *, codec: str | None, audio_seconds: float = 2.0) -> None:
    cmd = [
        _tools(), '-nostdin', '-hide_banner', '-loglevel', 'error',
        '-f', 'lavfi', '-i', 'testsrc=size=320x240:rate=24:duration=2',
    ]
    if codec:
        cmd += ['-f', 'lavfi', '-i', f'sine=frequency=440:sample_rate=48000:duration={audio_seconds}',
                '-map', '0:v:0', '-map', '1:a:0']
    else:
        cmd += ['-map', '0:v:0']
    cmd += ['-c:v', 'libx264', '-pix_fmt', 'yuv420p']
    if codec:
        cmd += ['-c:a', codec]
    cmd += ['-movflags', '+faststart', '-y', str(path)]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    assert p.returncode == 0, 'synthetic FFmpeg encode failed'


def _expected(path: Path) -> dict:
    return dict(path=path, expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                fps=24, frames=48, width=320, height=240)


def test_real_aac_lc_faststart_master_passes_full_audio_decode(tmp_path):
    path = tmp_path / 'aac.mp4'
    _encode(path, codec='aac')
    result = audio_gate.verify_mobile_audio(**_expected(path), require_audio=True)
    assert result['verified'] and result['full_decode_verified']
    assert result['mp4_faststart_verified'] and result['mobile_h264_8bit_420_verified']
    assert result['audio_present'] and result['mobile_aac_lc_verified']
    assert result['audio_full_decode_verified']
    assert result['owner_mobile_playback_verified'] is False
    assert str(path) not in json.dumps(result)


def test_real_alac_master_passes_prior_gates_but_fails_conservative_aac_gate(tmp_path):
    path = tmp_path / 'alac.mp4'
    _encode(path, codec='alac')
    # Reproduce the gap with actual FFmpeg media: prior SHA, video full-decode,
    # H.264 4:2:0 and faststart checks all pass despite non-AAC audio.
    assert verify_mobile_progressive(**_expected(path))['mp4_faststart_verified']
    with pytest.raises(audio_gate.VerificationFailure, match='mobile_audio_codec_unsupported'):
        audio_gate.verify_mobile_audio(**_expected(path), require_audio=True)


def test_real_short_aac_track_fails_duration_alignment(tmp_path):
    path = tmp_path / 'short.mp4'
    _encode(path, codec='aac', audio_seconds=1.0)
    assert verify_mobile_progressive(**_expected(path))['full_decode_verified']
    with pytest.raises(audio_gate.VerificationFailure, match='mobile_audio_duration_mismatch'):
        audio_gate.verify_mobile_audio(**_expected(path), require_audio=True)


def test_real_silent_master_optional_but_required_audio_fails(tmp_path):
    path = tmp_path / 'silent.mp4'
    _encode(path, codec=None)
    result = audio_gate.verify_mobile_audio(**_expected(path))
    assert result['verified'] and result['audio_absence_verified']
    assert result['mobile_aac_lc_verified'] is False
    with pytest.raises(audio_gate.VerificationFailure, match='mobile_audio_missing'):
        audio_gate.verify_mobile_audio(**_expected(path), require_audio=True)


def test_wrong_sha_rejected_before_audio_probe(monkeypatch, tmp_path):
    path = tmp_path / 'PRIVATE_OWNER_AUDIO.mp4'
    path.write_bytes(b'placeholder')
    monkeypatch.setattr(audio_gate, '_run', lambda *a, **kw: pytest.fail('audio probed'))
    with pytest.raises(audio_gate.VerificationFailure, match='hash_mismatch'):
        audio_gate.verify_mobile_audio(path, expected_sha256='0' * 64,
                                       fps=24, frames=48, width=320, height=240)


def test_cli_errors_are_privacy_minimized(monkeypatch, tmp_path, capsys):
    path = tmp_path / 'PRIVATE_OWNER_AUDIO.mp4'
    path.write_bytes(b'placeholder')
    monkeypatch.setattr(audio_gate, 'verify_mobile_audio', lambda *a, **kw: (
        (_ for _ in ()).throw(audio_gate.VerificationFailure('mobile_audio_probe_failed'))
    ))
    args = ['--mp4', str(path), '--expected-sha256', '0' * 64,
            '--fps', '24', '--frames', '48', '--width', '320', '--height', '240']
    assert audio_gate.main(args) == 2
    assert json.loads(capsys.readouterr().out) == {
        'verified': False, 'reason': 'mobile_audio_probe_failed',
    }


def test_unexpected_cli_error_does_not_expose_private_tool_output(monkeypatch, tmp_path, capsys):
    path = tmp_path / 'PRIVATE_OWNER_AUDIO.mp4'
    monkeypatch.setattr(audio_gate, 'verify_mobile_audio', lambda *a, **kw: (
        (_ for _ in ()).throw(RuntimeError('PRIVATE_OWNER_AUDIO.mp4 secret'))
    ))
    args = ['--mp4', str(path), '--expected-sha256', '0' * 64,
            '--fps', '24', '--frames', '48', '--width', '320', '--height', '240']
    assert audio_gate.main(args) == 2
    assert json.loads(capsys.readouterr().out) == {
        'verified': False, 'reason': 'verification_failed',
    }
