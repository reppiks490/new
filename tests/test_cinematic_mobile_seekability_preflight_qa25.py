"""QA25: genuine synthetic FFmpeg mobile seeking and packet-CFR acceptance.

A 4-second H.264 master with only its opening IDR remains fully decodable,
faststart and A/V-aligned, yet can require a multi-second decode after seeking.
No owner media, model inference, remote service or device is used.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from scripts import cinematic_mobile_seekability_preflight as gate
from scripts.cinematic_mobile_display_geometry_preflight import verify_mobile_display_geometry


def _tools() -> str:
    ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    if ffmpeg and ffprobe:
        probe = subprocess.run(
            [ffmpeg, '-hide_banner', '-encoders'], capture_output=True,
            text=True, timeout=20, check=False,
        )
        if probe.returncode == 0 and 'libx264' in probe.stdout and ' aac ' in probe.stdout:
            return ffmpeg
    if os.getenv('CINEMATIC_REQUIRE_REAL_MEDIA') == '1':
        pytest.fail('QA25 requires FFmpeg, FFprobe, libx264 and AAC')
    pytest.skip('synthetic FFmpeg tools unavailable')


def _encode(path: Path, *, gop: int, audio: bool = True) -> None:
    cmd = [
        _tools(), '-nostdin', '-hide_banner', '-loglevel', 'error',
        '-f', 'lavfi', '-i', 'testsrc=size=320x240:rate=24:duration=4',
    ]
    if audio:
        cmd += ['-f', 'lavfi', '-i',
                'sine=frequency=440:sample_rate=48000:duration=4']
    cmd += ['-map', '0:v:0']
    if audio:
        cmd += ['-map', '1:a:0']
    cmd += ['-c:v', 'libx264', '-g', str(gop), '-keyint_min', str(gop),
            '-sc_threshold', '0', '-pix_fmt', 'yuv420p']
    if audio:
        cmd += ['-c:a', 'aac']
    cmd += ['-movflags', '+faststart', '-y', str(path)]
    result = subprocess.run(cmd, capture_output=True, text=True,
                            timeout=180, check=False)
    assert result.returncode == 0, 'synthetic media generation failed'


def _expect(path: Path) -> dict:
    return {
        'path': path, 'expected_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'fps': 24, 'frames': 96, 'width': 320, 'height': 240,
    }


def test_real_periodic_keyframes_pass_full_mobile_acceptance(tmp_path):
    path = tmp_path / 'PRIVATE_PERIODIC.mp4'
    _encode(path, gop=24)
    result = gate.verify_mobile_seekability(**_expect(path), require_audio=True)
    assert result['verified'] and result['full_decode_verified']
    assert result['mobile_keyframe_seek_window_verified']
    assert result['mobile_video_packet_cfr_verified']
    assert result['keyframe_count'] >= 4
    assert result['max_keyframe_gap_seconds'] <= 2.0
    assert result['owner_mobile_playback_verified'] is False
    assert str(path) not in json.dumps(result)


def test_real_single_idr_passes_previous_gates_but_fails_seek_window(tmp_path):
    path = tmp_path / 'PRIVATE_SINGLE_IDR.mp4'
    _encode(path, gop=240)
    # Test-first control: prior SHA, decode, H.264, faststart, AAC,
    # timestamp and display-geometry acceptance cannot bound seek GOP.
    prior = verify_mobile_display_geometry(**_expect(path), require_audio=True)
    assert prior['verified'] and prior['mobile_square_pixels_verified']
    with pytest.raises(gate.VerificationFailure, match='mobile_seek_keyframe_gap_exceeded'):
        gate.verify_mobile_seekability(**_expect(path), require_audio=True)


def test_real_silent_master_is_allowed_without_audio_requirement(tmp_path):
    path = tmp_path / 'PRIVATE_SILENT.mp4'
    _encode(path, gop=24, audio=False)
    result = gate.verify_mobile_seekability(**_expect(path))
    assert result['verified'] and result['audio_absence_verified']
    with pytest.raises(gate.VerificationFailure, match='mobile_audio_missing'):
        gate.verify_mobile_seekability(**_expect(path), require_audio=True)


def test_wrong_sha_stops_before_packet_probe(tmp_path, monkeypatch):
    path = tmp_path / 'PRIVATE_HASH.mp4'
    _encode(path, gop=24)
    monkeypatch.setattr(gate, '_run', lambda *a, **kw: pytest.fail('packet probe called'))
    with pytest.raises(gate.VerificationFailure, match='hash_mismatch'):
        gate.verify_mobile_seekability(
            path, expected_sha256='0' * 64, fps=24, frames=96,
            width=320, height=240,
        )


@pytest.mark.parametrize('payload', [
    {'packets': [{'pts_time': '0', 'flags': 'K__'}]},
    {'packets': [{'pts_time': 'nan', 'flags': 'K__'}] * 96},
    {'packets': [{'pts_time': '0'}] * 96},
    {'packets': 'PRIVATE_BAD_PACKET'},
])
def test_invalid_packet_probe_fails_closed(monkeypatch, tmp_path, payload):
    monkeypatch.setattr(gate, 'verify_mobile_display_geometry', lambda *a, **kw: {
        'verified': True, 'duration_seconds': 4.0,
    })
    monkeypatch.setattr(gate, '_run', lambda *a, **kw: subprocess.CompletedProcess(
        [], 0, json.dumps(payload), '',
    ))
    with pytest.raises(gate.VerificationFailure, match='mobile_seek_packet_probe_invalid'):
        gate.verify_mobile_seekability(
            tmp_path / 'PRIVATE.mp4', expected_sha256='0' * 64,
            fps=24, frames=96, width=320, height=240,
        )


def test_cli_hides_private_paths_and_unexpected_errors(monkeypatch, tmp_path, capsys):
    path = tmp_path / 'PRIVATE_OWNER_PATH.mp4'
    def fail(*a, **kw):
        raise RuntimeError('PRIVATE_OWNER_PATH.mp4 secret media tag')
    monkeypatch.setattr(gate, 'verify_mobile_seekability', fail)
    args = ['--mp4', str(path), '--expected-sha256', '0' * 64,
            '--fps', '24', '--frames', '96', '--width', '320', '--height', '240']
    assert gate.main(args) == 2
    assert json.loads(capsys.readouterr().out) == {
        'verified': False, 'reason': 'verification_failed',
    }
