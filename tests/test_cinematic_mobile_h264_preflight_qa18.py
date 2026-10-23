"""Genuine synthetic FFmpeg and isolated privacy tests for mobile H.264 profile."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from scripts import cinematic_mobile_h264_preflight as preflight


def _expected(path: Path) -> dict:
    return {
        'path': path,
        'expected_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'fps': 24, 'frames': 48, 'width': 320, 'height': 240,
    }


def _require_real_media():
    ffmpeg = shutil.which('ffmpeg')
    ffprobe = shutil.which('ffprobe')
    if ffmpeg and ffprobe:
        encoders = subprocess.run(
            [ffmpeg, '-hide_banner', '-encoders'],
            capture_output=True, text=True, check=False, timeout=20,
        )
        if encoders.returncode == 0 and 'libx264' in encoders.stdout:
            return ffmpeg
    if os.environ.get('CINEMATIC_REQUIRE_REAL_MEDIA') == '1':
        pytest.fail('strict media QA requires ffmpeg, ffprobe and libx264')
    pytest.skip('real FFmpeg/libx264 not installed in general CI')


def _encode(path: Path, pix_fmt: str) -> None:
    ffmpeg = _require_real_media()
    completed = subprocess.run([
        ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error',
        '-f', 'lavfi', '-i', 'testsrc=size=320x240:rate=24:duration=2',
        '-c:v', 'libx264', '-pix_fmt', pix_fmt,
        '-movflags', '+faststart', '-y', str(path),
    ], capture_output=True, text=True, timeout=120, check=False)
    assert completed.returncode == 0, 'synthetic libx264 fixture generation failed'


def test_real_8bit_420_h264_is_accepted_with_strict_decode(tmp_path):
    path = tmp_path / 'synthetic-420.mp4'
    _encode(path, 'yuv420p')
    result = preflight.verify_mobile_h264(**_expected(path))
    assert result['verified'] and result['full_decode_verified']
    assert result['mobile_h264_8bit_420_verified'] is True
    assert result['owner_mobile_playback_verified'] is False
    assert str(path) not in json.dumps(result)


def test_real_444_h264_decodes_but_is_rejected_as_mobile_profile(tmp_path):
    path = tmp_path / 'synthetic-444.mp4'
    _encode(path, 'yuv444p')
    # Distinct gap: H.264 codec, frame count, SHA and full FFmpeg decode are
    # all valid, yet 4:4:4 High Predictive is not a mobile-safe H.264 profile.
    from scripts.cinematic_master_acceptance import verify_master
    assert verify_master(**_expected(path))['full_decode_verified']
    with pytest.raises(preflight.VerificationFailure, match='mobile_profile_unsupported'):
        preflight.verify_mobile_h264(**_expected(path))


def test_hash_mismatch_fails_before_mobile_profile_probe(monkeypatch, tmp_path):
    path = tmp_path / 'private.mp4'
    path.write_bytes(b'not a real MP4')
    monkeypatch.setattr(preflight, '_run', lambda *args, **kwargs: pytest.fail('probe invoked'))
    with pytest.raises(preflight.VerificationFailure, match='hash_mismatch'):
        preflight.verify_mobile_h264(
            path, expected_sha256='0' * 64,
            fps=24, frames=48, width=320, height=240,
        )


def test_cli_hides_owner_path_and_tool_stderr(monkeypatch, tmp_path, capsys):
    path = tmp_path / 'PRIVATE_OWNER_FOOTAGE.mp4'
    path.write_bytes(b'placeholder')
    monkeypatch.setattr(preflight, 'verify_master', lambda *args, **kwargs: {'verified': True})
    monkeypatch.setattr(preflight, '_run', lambda *args, **kwargs: subprocess.CompletedProcess(
        args[0], 1, '', 'PRIVATE_TOKEN_AND_PATH',
    ))
    args = [
        '--mp4', str(path), '--expected-sha256', hashlib.sha256(path.read_bytes()).hexdigest(),
        '--fps', '24', '--frames', '48', '--width', '320', '--height', '240',
    ]
    assert preflight.main(args) == 2
    output = capsys.readouterr().out
    assert json.loads(output) == {'verified': False, 'reason': 'mobile_probe_failed'}
    assert 'PRIVATE_' not in output


def test_malformed_mobile_probe_fails_closed(monkeypatch, tmp_path):
    path = tmp_path / 'private.mp4'
    path.write_bytes(b'placeholder')
    monkeypatch.setattr(preflight, 'verify_master', lambda *args, **kwargs: {'verified': True})
    monkeypatch.setattr(preflight, '_run', lambda *args, **kwargs: subprocess.CompletedProcess(
        args[0], 0, '{"streams":[],"format":{}}', '',
    ))
    with pytest.raises(preflight.VerificationFailure, match='mobile_probe_invalid'):
        preflight.verify_mobile_h264(**_expected(path))
