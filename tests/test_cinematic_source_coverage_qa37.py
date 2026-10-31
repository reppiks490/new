"""QA37: local synthetic source underlength versus FFmpeg master frame count."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from app.video.cinematic_source_coverage_qa37 import (
    SourceCoverageProbeError, assess_source_probe, audit_source_file,
)


def _probe(duration='1.000000', *, frames='24', fps='24/1'):
    return {'format': {'duration': '9999'}, 'streams': [{
        'codec_type': 'video', 'duration': duration,
        'avg_frame_rate': fps, 'nb_frames': frames,
    }]}


def test_detects_short_source_even_when_container_audio_is_longer():
    result = assess_source_probe(_probe(), required_frames=72, delivery_fps=24)
    assert result['coverage'] == 'underlength'
    assert result['shortfall_seconds'] == pytest.approx(2)
    assert result['source_reported_frames'] == 24
    assert result['source_fps'] == '24'
    assert not any('path' in key or 'prompt' in key for key in result)


def test_nominal_source_and_rounding_band():
    assert assess_source_probe(_probe('3'), required_frames=72, delivery_fps=24)['coverage'] == 'nominal'
    assert assess_source_probe(_probe('2.99'), required_frames=72, delivery_fps=24)['coverage'] == 'nominal'
    assert assess_source_probe(_probe('2.95'), required_frames=72, delivery_fps=24)['coverage'] == 'underlength'


def test_missing_stream_duration_is_unknown_not_container_duration():
    result = assess_source_probe(_probe('N/A'), required_frames=72, delivery_fps=24)
    assert result['coverage'] == 'unknown'
    assert result['observed_video_seconds'] is None
    assert result['shortfall_seconds'] is None


@pytest.mark.parametrize('value', [float('nan'), 0, -1, 'N/A', None])
def test_invalid_stream_durations_do_not_claim_coverage(value):
    assert assess_source_probe(_probe(value), required_frames=24, delivery_fps=24)['coverage'] == 'unknown'


@pytest.mark.parametrize('frames,fps', [(0, 24), (72001, 24), (1, 0), (1, 121), (True, 24), (1, 24.0)])
def test_rejects_invalid_frame_policy(frames, fps):
    with pytest.raises(ValueError):
        assess_source_probe(_probe(), required_frames=frames, delivery_fps=fps)


def test_rejects_missing_or_ambiguous_video_stream():
    with pytest.raises(SourceCoverageProbeError):
        assess_source_probe({'streams': []}, required_frames=24, delivery_fps=24)
    with pytest.raises(SourceCoverageProbeError):
        assess_source_probe({'streams': _probe()['streams'] * 2}, required_frames=24, delivery_fps=24)


def test_probe_error_does_not_echo_private_file_path(tmp_path):
    secret = tmp_path / 'PRIVATE_OWNER_SCREENPLAY_DO_NOT_ECHO.mp4'
    with pytest.raises(SourceCoverageProbeError) as error:
        audit_source_file(secret, required_frames=24, delivery_fps=24)
    assert 'PRIVATE_OWNER' not in str(error.value)
    assert 'SCREENPLAY' not in str(error.value)


def test_real_synthetic_short_source_is_padded_to_valid_length(tmp_path: Path):
    ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        if os.getenv('CINEMATIC_REQUIRE_REAL_MEDIA') == '1':
            pytest.fail('QA37 requires FFmpeg and FFprobe')
        pytest.skip('FFmpeg and FFprobe unavailable')
    source, output = tmp_path / 'source.mp4', tmp_path / 'master.mp4'
    def run(args):
        return subprocess.run(args, check=True, capture_output=True, timeout=90)
    run([ffmpeg, '-nostdin', '-y', '-v', 'error', '-f', 'lavfi', '-i',
         'testsrc2=s=160x90:r=24:d=1', '-an', '-c:v', 'libx264',
         '-pix_fmt', 'yuv420p', str(source)])
    audit = audit_source_file(source, required_frames=72, delivery_fps=24)
    assert audit['coverage'] == 'underlength'
    assert audit['shortfall_seconds'] == pytest.approx(2)
    # Mirrors the *actual* production fps/tpad/trim/concat path for one shot.
    run([ffmpeg, '-nostdin', '-y', '-v', 'error', '-i', str(source),
         '-filter_complex',
         '[0:v:0]fps=24,scale=160:90:force_original_aspect_ratio=decrease,'
         'pad=160:90:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p,'
         'tpad=stop_mode=clone:stop=72,trim=end_frame=72,setpts=PTS-STARTPTS[v]',
         '-map', '[v]', '-an', '-c:v', 'libx264', '-r', '24',
         '-fps_mode', 'cfr', str(output)])
    metadata = json.loads(run([ffprobe, '-v', 'error', '-select_streams', 'v:0',
                               '-show_entries', 'stream=nb_frames,duration',
                               '-of', 'json', str(output)]).stdout)
    assert int(metadata['streams'][0]['nb_frames']) == 72
    assert float(metadata['streams'][0]['duration']) == pytest.approx(3, abs=0.05)
    run([ffmpeg, '-nostdin', '-v', 'error', '-xerror', '-i', str(output),
         '-an', '-f', 'null', '-'])
    # This demonstrates a playable output can conceal a source under-run.
