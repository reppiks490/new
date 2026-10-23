"""QA22: genuine synthetic FFmpeg A/V presentation alignment and privacy."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from scripts import cinematic_mobile_av_sync_preflight as gate
from scripts.cinematic_mobile_audio_preflight import verify_mobile_audio


def _ffmpeg() -> str:
    ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    if ffmpeg and ffprobe:
        p = subprocess.run([ffmpeg, '-hide_banner', '-encoders'], capture_output=True,
                           text=True, timeout=20, check=False)
        if p.returncode == 0 and 'libx264' in p.stdout and ' aac ' in p.stdout:
            return ffmpeg
    if os.environ.get('CINEMATIC_REQUIRE_REAL_MEDIA') == '1':
        pytest.fail('QA22 requires FFmpeg, FFprobe, libx264 and AAC')
    pytest.skip('genuine synthetic media tools unavailable')


def _encode(path: Path, *, delayed: bool = False, audio: bool = True) -> None:
    cmd = [_ffmpeg(), '-nostdin', '-hide_banner', '-loglevel', 'error',
           '-f', 'lavfi', '-i', 'testsrc=size=320x240:rate=24:duration=2']
    if audio:
        # AAC priming means 120ms input offset appears as ~98ms start_time.
        # 1.88s audio ends at 2.0s: duration-only QA21 passes, but the
        # opening 98ms of video has no corresponding audio presentation.
        if delayed:
            cmd += ['-itsoffset', '0.12']
        cmd += ['-f', 'lavfi', '-i',
                f'sine=frequency=440:sample_rate=48000:duration={1.88 if delayed else 2}']
        cmd += ['-map', '0:v:0', '-map', '1:a:0']
    else:
        cmd += ['-map', '0:v:0']
    cmd += ['-c:v', 'libx264', '-pix_fmt', 'yuv420p']
    if audio:
        cmd += ['-c:a', 'aac']
    cmd += ['-movflags', '+faststart', '-y', str(path)]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    assert p.returncode == 0, 'synthetic FFmpeg encoding failed'


def _expect(path: Path) -> dict:
    return dict(path=path, expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                fps=24, frames=48, width=320, height=240)


def test_real_aligned_aac_passes_with_private_minimal_result(tmp_path):
    path = tmp_path / 'private_aligned.mp4'
    _encode(path)
    result = gate.verify_mobile_av_sync(**_expect(path), require_audio=True)
    assert result['verified'] and result['av_stream_timing_verified']
    assert result['audio_full_decode_verified']
    assert result['av_start_skew_seconds'] <= 0.050
    assert result['av_end_skew_seconds'] <= 0.050
    assert result['owner_mobile_playback_verified'] is False
    assert str(path) not in json.dumps(result)


def test_real_delayed_aac_passes_duration_only_but_fails_timestamp_gate(tmp_path):
    path = tmp_path / 'private_delayed.mp4'
    _encode(path, delayed=True)
    # Concrete RED-before-fix reproduction: existing QA21 gate accepts this
    # 48-frame MP4, despite its ~98ms delayed audio presentation start.
    prior = verify_mobile_audio(**_expect(path), require_audio=True)
    assert prior['verified'] and prior['mobile_aac_lc_verified']
    with pytest.raises(gate.VerificationFailure, match='mobile_av_presentation_mismatch'):
        gate.verify_mobile_av_sync(**_expect(path), require_audio=True)


def test_real_silent_film_not_mislabeled_as_av_verified(tmp_path):
    path = tmp_path / 'private_silent.mp4'
    _encode(path, audio=False)
    result = gate.verify_mobile_av_sync(**_expect(path))
    assert result['verified'] and result['av_stream_timing_not_applicable']
    assert result['av_stream_timing_verified'] is False
    with pytest.raises(gate.VerificationFailure, match='mobile_audio_missing'):
        gate.verify_mobile_av_sync(**_expect(path), require_audio=True)


def test_wrong_sha_fails_before_av_timing_probe(tmp_path, monkeypatch):
    path = tmp_path / 'private_bad_hash.mp4'
    _encode(path)
    monkeypatch.setattr(gate, '_run', lambda *a, **kw: pytest.fail('av timing probed'))
    with pytest.raises(gate.VerificationFailure, match='hash_mismatch'):
        gate.verify_mobile_av_sync(path, expected_sha256='0' * 64,
                                   fps=24, frames=48, width=320, height=240)


def test_unexpected_probe_fields_fail_closed(monkeypatch, tmp_path):
    monkeypatch.setattr(gate, 'verify_mobile_audio', lambda *a, **kw: {
        'verified': True, 'audio_present': True,
    })
    monkeypatch.setattr(gate, '_run', lambda *a, **kw: subprocess.CompletedProcess(
        [], 0, json.dumps({'streams': [
            {'codec_type': 'video', 'start_time': '0', 'duration': '2'},
            {'codec_type': 'audio', 'start_time': 'nan', 'duration': '2'},
        ]}), '',
    ))
    with pytest.raises(gate.VerificationFailure, match='mobile_av_timing_probe_invalid'):
        gate.verify_mobile_av_sync(tmp_path / 'private.mp4', expected_sha256='0' * 64,
                                   fps=24, frames=48, width=320, height=240)


def test_cli_does_not_expose_private_paths_or_tool_errors(tmp_path, monkeypatch, capsys):
    path = tmp_path / 'PRIVATE_MEDIA_NAME.mp4'
    monkeypatch.setattr(gate, 'verify_mobile_av_sync', lambda *a, **kw: (
        (_ for _ in ()).throw(RuntimeError('PRIVATE_MEDIA_NAME.mp4 owner secret'))
    ))
    args = ['--mp4', str(path), '--expected-sha256', '0' * 64,
            '--fps', '24', '--frames', '48', '--width', '320', '--height', '240']
    assert gate.main(args) == 2
    assert json.loads(capsys.readouterr().out) == {
        'verified': False, 'reason': 'verification_failed',
    }
