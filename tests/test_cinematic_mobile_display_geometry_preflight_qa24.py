"""QA24: real synthetic H.264 SAR/rotation metadata acceptance; no owner media."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from scripts import cinematic_mobile_display_geometry_preflight as gate
from scripts.cinematic_mobile_av_sync_preflight import verify_mobile_av_sync


def _tools() -> tuple[str, str]:
    ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    if ffmpeg and ffprobe:
        p = subprocess.run([ffmpeg, '-hide_banner', '-encoders'], capture_output=True,
                           text=True, timeout=20, check=False)
        if p.returncode == 0 and 'libx264' in p.stdout:
            return ffmpeg, ffprobe
    if os.environ.get('CINEMATIC_REQUIRE_REAL_MEDIA') == '1':
        pytest.fail('QA24 requires real FFmpeg/FFprobe/libx264')
    pytest.skip('genuine synthetic media tools unavailable')


def _encode(path: Path, *, anamorphic: bool = False) -> None:
    ffmpeg, _ = _tools()
    cmd = [ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error',
           '-f', 'lavfi', '-i', 'testsrc2=size=320x240:rate=24:duration=2']
    if anamorphic:
        cmd += ['-vf', 'setsar=4/3']
    cmd += ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
            '-y', str(path)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    assert result.returncode == 0, 'synthetic FFmpeg encoding failed'


def _rotate(source: Path, target: Path) -> None:
    ffmpeg, _ = _tools()
    # Input display_rotation creates an MP4 displaymatrix without altering
    # the H.264 bitstream, so older SHA/decode/profile gates still accept it.
    result = subprocess.run([
        ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error',
        '-display_rotation', '90', '-i', str(source), '-c', 'copy',
        '-movflags', '+faststart', '-y', str(target),
    ], capture_output=True, text=True, timeout=120, check=False)
    assert result.returncode == 0, 'synthetic FFmpeg rotation metadata failed'
    _, ffprobe = _tools()
    p = subprocess.run([
        ffprobe, '-v', 'error', '-show_entries', 'stream_side_data=rotation',
        '-of', 'json', str(target),
    ], capture_output=True, text=True, timeout=20, check=False)
    assert p.returncode == 0 and '90' in p.stdout, 'rotation fixture not encoded'


def _expect(path: Path) -> dict:
    return dict(path=path, expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                fps=24, frames=48, width=320, height=240)


def test_normalized_synthetic_mp4_passes_without_claiming_phone_playback(tmp_path):
    path = tmp_path / 'private_normal.mp4'
    _encode(path)
    result = gate.verify_mobile_display_geometry(**_expect(path))
    assert result['verified'] and result['mobile_square_pixels_verified']
    assert result['mobile_no_display_transform_verified']
    assert result['owner_mobile_playback_verified'] is False
    assert str(path) not in json.dumps(result)


def test_anamorphic_synthetic_mp4_passes_old_gate_but_fails_geometry(tmp_path):
    path = tmp_path / 'private_anamorphic.mp4'
    _encode(path, anamorphic=True)
    assert verify_mobile_av_sync(**_expect(path))['verified']
    with pytest.raises(gate.VerificationFailure, match='mobile_display_geometry_unsupported'):
        gate.verify_mobile_display_geometry(**_expect(path))


def test_rotated_synthetic_mp4_passes_old_gate_but_fails_geometry(tmp_path):
    source = tmp_path / 'private_base.mp4'
    rotated = tmp_path / 'private_rotated.mp4'
    _encode(source)
    _rotate(source, rotated)
    assert verify_mobile_av_sync(**_expect(rotated))['verified']
    with pytest.raises(gate.VerificationFailure, match='mobile_display_geometry_unsupported'):
        gate.verify_mobile_display_geometry(**_expect(rotated))


def test_wrong_sha_rejected_before_display_probe(tmp_path, monkeypatch):
    path = tmp_path / 'private_bad_hash.mp4'
    _encode(path)
    monkeypatch.setattr(gate, '_run', lambda *a, **kw: pytest.fail('geometry probe must not run'))
    with pytest.raises(gate.VerificationFailure, match='hash_mismatch'):
        gate.verify_mobile_display_geometry(path, expected_sha256='0' * 64,
                                            fps=24, frames=48, width=320, height=240)


def test_malformed_geometry_probe_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, 'verify_mobile_av_sync', lambda *a, **kw: {'verified': True})
    monkeypatch.setattr(gate, '_run', lambda *a, **kw: subprocess.CompletedProcess(
        [], 0, json.dumps({'streams': [{'codec_type': 'video',
                                       'sample_aspect_ratio': '1:1',
                                       'side_data_list': 'malformed'}]}), '',
    ))
    with pytest.raises(gate.VerificationFailure, match='mobile_display_probe_invalid'):
        gate.verify_mobile_display_geometry(tmp_path / 'private.mp4', expected_sha256='0' * 64,
                                            fps=24, frames=48, width=320, height=240)


def test_cli_failure_never_exposes_private_paths_or_tool_stderr(tmp_path, monkeypatch, capsys):
    path = tmp_path / 'OWNER_PRIVATE_PATH.mp4'
    monkeypatch.setattr(gate, 'verify_mobile_display_geometry', lambda *a, **kw: (
        (_ for _ in ()).throw(RuntimeError('OWNER_PRIVATE_PATH.mp4 owner secret'))
    ))
    args = ['--mp4', str(path), '--expected-sha256', '0' * 64,
            '--fps', '24', '--frames', '48', '--width', '320', '--height', '240']
    assert gate.main(args) == 2
    assert json.loads(capsys.readouterr().out) == {
        'verified': False, 'reason': 'verification_failed',
    }
