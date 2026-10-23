"""Real synthetic FFmpeg and bounded read-only MP4 atom/privacy tests (QA19)."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from scripts import cinematic_mobile_progressive_preflight as progressive
from scripts.cinematic_mobile_h264_preflight import verify_mobile_h264


def _expected(path: Path) -> dict:
    return {
        'path': path,
        'expected_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'fps': 24, 'frames': 48, 'width': 320, 'height': 240,
    }


def _ffmpeg() -> str:
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
        pytest.fail('strict QA19 requires ffmpeg, ffprobe and libx264')
    pytest.skip('real FFmpeg/libx264 not installed in general CI')


def _encode(path: Path, *, faststart: bool) -> None:
    ffmpeg = _ffmpeg()
    command = [
        ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error',
        '-f', 'lavfi', '-i', 'testsrc=size=320x240:rate=24:duration=2',
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
    ]
    if faststart:
        command.extend(['-movflags', '+faststart'])
    command.extend(['-y', str(path)])
    completed = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    assert completed.returncode == 0, 'synthetic fixture encoding failed'


def test_real_faststart_mp4_passes_after_sha_full_decode_and_profile(tmp_path):
    path = tmp_path / 'synthetic-faststart.mp4'
    _encode(path, faststart=True)
    result = progressive.verify_mobile_progressive(**_expected(path))
    assert result['verified'] and result['full_decode_verified']
    assert result['mobile_h264_8bit_420_verified']
    assert result['mp4_faststart_verified']
    assert result['private_http_range_verified'] is False
    assert result['owner_mobile_playback_verified'] is False
    assert str(path) not in json.dumps(result)


def test_real_tail_moov_is_valid_h264_but_not_progressive_ready(tmp_path):
    path = tmp_path / 'synthetic-tail-moov.mp4'
    _encode(path, faststart=False)
    # This is the reproduced gap: QA18 passes SHA, decode and H.264 profile,
    # but the MP4 metadata follows mdat, delaying progressive startup.
    assert verify_mobile_h264(**_expected(path))['mobile_h264_8bit_420_verified']
    with pytest.raises(progressive.VerificationFailure, match='mp4_faststart_missing'):
        progressive.verify_mobile_progressive(**_expected(path))


def test_bad_sha_rejected_before_atom_inspection(monkeypatch, tmp_path):
    path = tmp_path / 'PRIVATE_OWNER_MEDIA.mp4'
    path.write_bytes(b'placeholder')
    monkeypatch.setattr(progressive, '_scan_top_level_boxes', lambda *args: pytest.fail('atoms scanned'))
    with pytest.raises(progressive.VerificationFailure, match='hash_mismatch'):
        progressive.verify_mobile_progressive(
            path, expected_sha256='0' * 64,
            fps=24, frames=48, width=320, height=240,
        )


def _box(tag: bytes, data: bytes = b'') -> bytes:
    return (8 + len(data)).to_bytes(4, 'big') + tag + data


def test_extended_size_moov_atom_is_parsed(tmp_path):
    path = tmp_path / 'extended.mp4'
    moov = (1).to_bytes(4, 'big') + b'moov' + (16).to_bytes(8, 'big')
    path.write_bytes(_box(b'ftyp', b'isom') + moov + _box(b'mdat', b'1234'))
    progressive._scan_top_level_boxes(path)


@pytest.mark.parametrize('bad', [
    b'garbage',
    _box(b'ftyp', b'isom') + b'\x00\x00\x00\x04moov' + _box(b'mdat'),
    _box(b'ftyp') + _box(b'moov') + _box(b'moov') + _box(b'mdat'),
    _box(b'ftyp') + _box(b'moov') + _box(b'mdat') + b'X',
])
def test_malformed_or_duplicate_atoms_fail_closed(tmp_path, bad):
    path = tmp_path / 'bad.mp4'
    path.write_bytes(bad)
    with pytest.raises(progressive.VerificationFailure, match='mp4_atom_invalid'):
        progressive._scan_top_level_boxes(path)


def test_fragmented_mp4_rejected_by_progressive_gate(tmp_path):
    path = tmp_path / 'fragmented.mp4'
    path.write_bytes(_box(b'ftyp') + _box(b'moov') + _box(b'moof') + _box(b'mdat'))
    with pytest.raises(progressive.VerificationFailure, match='mp4_fragmented_unsupported'):
        progressive._scan_top_level_boxes(path)


def test_cli_failure_never_prints_owner_path_or_tool_stderr(monkeypatch, tmp_path, capsys):
    path = tmp_path / 'PRIVATE_OWNER_MEDIA.mp4'
    path.write_bytes(b'placeholder')
    monkeypatch.setattr(progressive, 'verify_mobile_progressive', lambda *a, **kw: (
        (_ for _ in ()).throw(progressive.VerificationFailure('mp4_faststart_missing'))
    ))
    args = [
        '--mp4', str(path), '--expected-sha256', hashlib.sha256(path.read_bytes()).hexdigest(),
        '--fps', '24', '--frames', '48', '--width', '320', '--height', '240',
    ]
    assert progressive.main(args) == 2
    output = capsys.readouterr().out
    assert json.loads(output) == {'verified': False, 'reason': 'mp4_faststart_missing'}
    assert 'PRIVATE_' not in output
