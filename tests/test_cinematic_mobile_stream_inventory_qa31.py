"""QA31: genuine synthetic MP4 stream-inventory privacy/mobile regression.

The older QA17 first-video SHA/decode gate can accept extra tracks. These
tests prove that specific acceptance blind spot before exercising a separate,
opt-in closed-stream gate. They do NOT demonstrate that production assembly
currently emits auxiliary tracks or that an iPhone has played these files.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.cinematic_master_acceptance import VerificationFailure, verify_master
from scripts import cinematic_mobile_stream_inventory_preflight_qa31 as qa

pytestmark = pytest.mark.skipif(
    os.getenv('CINEMATIC_REQUIRE_STREAM_INVENTORY_QA') != '1',
    reason='Opt-in real synthetic FFmpeg stream inventory QA31',
)


def _tools() -> tuple[str, str]:
    ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        pytest.fail('Strict QA31 requires FFmpeg and FFprobe')
    return ffmpeg, ffprobe


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True, capture_output=True, text=True, timeout=120)


def _source(tmp_path: Path) -> Path:
    ffmpeg, _ = _tools()
    source = tmp_path / 'synthetic_clean.mp4'
    _run([
        ffmpeg, '-nostdin', '-y', '-v', 'error',
        '-f', 'lavfi', '-i', 'color=c=red:s=160x90:r=24:d=2',
        '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
        '-movflags', '+faststart', str(source),
    ])
    return source


def _hash(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def _args(path: Path) -> dict:
    ffmpeg, ffprobe = _tools()
    return {
        'path': path, 'expected_sha256': _hash(path),
        'fps': 24, 'frames': 48, 'width': 160, 'height': 90,
        'ffmpeg': ffmpeg, 'ffprobe': ffprobe,
    }


def test_single_video_master_passes_closed_stream_inventory(tmp_path):
    clean = _source(tmp_path)
    result = qa.verify_master_stream_inventory(**_args(clean))
    assert result['verified'] is True
    assert result['full_decode_verified'] is True
    assert result['stream_inventory_verified'] is True
    assert result['video_stream_count'] == 1
    assert result['audio_stream_count'] == 0
    assert result['owner_mobile_playback_verified'] is False


def test_legacy_first_video_gate_accepts_hidden_second_video_stream(tmp_path):
    ffmpeg, _ = _tools()
    dual = tmp_path / 'synthetic_dual_video.mp4'
    _run([
        ffmpeg, '-nostdin', '-y', '-v', 'error',
        '-f', 'lavfi', '-i', 'color=c=red:s=160x90:r=24:d=2',
        '-f', 'lavfi', '-i', 'color=c=blue:s=160x90:r=24:d=2',
        '-map', '0:v:0', '-map', '1:v:0', '-an',
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
        '-movflags', '+faststart', str(dual),
    ])
    expectations = _args(dual)
    # The previous acceptance validates and decodes only 0:v:0.
    assert verify_master(**expectations)['verified'] is True
    with pytest.raises(VerificationFailure) as failure:
        qa.verify_master_stream_inventory(**expectations)
    assert failure.value.reason == 'unexpected_video_stream_count'


def test_legacy_first_video_gate_accepts_embedded_subtitle_stream(tmp_path):
    ffmpeg, _ = _tools()
    clean = _source(tmp_path)
    subtitle = tmp_path / 'synthetic.srt'
    subtitle.write_text(
        '1\n00:00:00,000 --> 00:00:01,000\nSYNTHETIC_QA_ONLY\n',
        encoding='utf-8',
    )
    with_subtitle = tmp_path / 'synthetic_subtitle.mp4'
    _run([
        ffmpeg, '-nostdin', '-y', '-v', 'error',
        '-i', str(clean), '-f', 'srt', '-i', str(subtitle),
        '-map', '0:v:0', '-map', '1:0',
        '-c:v', 'copy', '-c:s', 'mov_text',
        '-movflags', '+faststart', str(with_subtitle),
    ])
    expectations = _args(with_subtitle)
    assert verify_master(**expectations)['verified'] is True
    with pytest.raises(VerificationFailure) as failure:
        qa.verify_master_stream_inventory(**expectations)
    assert failure.value.reason == 'unexpected_auxiliary_stream'


def _audio_master(tmp_path: Path, codec: str) -> Path:
    ffmpeg, _ = _tools()
    clean = _source(tmp_path)
    result = tmp_path / f'synthetic_{codec}.mp4'
    _run([
        ffmpeg, '-nostdin', '-y', '-v', 'error',
        '-i', str(clean),
        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=2',
        '-map', '0:v:0', '-map', '1:a:0',
        '-c:v', 'copy', '-c:a', codec,
        '-shortest', '-movflags', '+faststart', str(result),
    ])
    return result


def test_audio_requires_explicit_policy_and_reports_no_audio_decode(tmp_path):
    aac = _audio_master(tmp_path, 'aac')
    expectations = _args(aac)
    with pytest.raises(VerificationFailure) as failure:
        qa.verify_master_stream_inventory(**expectations)
    assert failure.value.reason == 'unexpected_audio_stream'
    result = qa.verify_master_stream_inventory(**expectations, allow_aac_audio=True)
    assert result['audio_stream_count'] == 1
    assert result['audio_decode_verified'] is False
    assert result['owner_mobile_playback_verified'] is False


def test_non_aac_audio_rejected_even_when_audio_is_allowed(tmp_path):
    alac = _audio_master(tmp_path, 'alac')
    with pytest.raises(VerificationFailure) as failure:
        qa.verify_master_stream_inventory(**_args(alac), allow_aac_audio=True)
    assert failure.value.reason == 'unexpected_audio_codec'


def test_hash_mismatch_fails_before_stream_inventory(tmp_path, monkeypatch):
    clean = _source(tmp_path)
    def should_not_probe(*args, **kwargs):
        raise AssertionError('stream inventory ran before trusted SHA gate')
    monkeypatch.setattr(qa, '_run', should_not_probe)
    with pytest.raises(VerificationFailure) as failure:
        qa.verify_master_stream_inventory(
            **{**_args(clean), 'expected_sha256': '0' * 64}
        )
    assert failure.value.reason == 'hash_mismatch'


def test_malformed_stream_inventory_is_rejected_without_echoing_probe(tmp_path, monkeypatch):
    clean = _source(tmp_path)
    monkeypatch.setattr(
        qa, '_run',
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps({'streams': [{'codec_type': 'video'}],
                               'format': {'format_name': 'mov,mp4'}}),
        ),
    )
    with pytest.raises(VerificationFailure) as failure:
        qa.verify_master_stream_inventory(**_args(clean))
    assert failure.value.reason == 'stream_inventory_invalid'
    assert str(clean) not in str(failure.value)


def test_cli_failure_does_not_print_local_media_path(tmp_path, capsys):
    clean = _source(tmp_path)
    ffmpeg, ffprobe = _tools()
    exit_code = qa.main([
        '--mp4', str(clean), '--expected-sha256', '0' * 64,
        '--fps', '24', '--frames', '48',
        '--width', '160', '--height', '90',
        '--ffmpeg', ffmpeg, '--ffprobe', ffprobe,
    ])
    output = capsys.readouterr().out
    assert exit_code == 2
    assert json.loads(output) == {'verified': False, 'reason': 'hash_mismatch'}
    assert str(tmp_path) not in output
