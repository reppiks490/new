"""QA27: private filtergraph scripts bypass the QA26 Linux E2BIG boundary.

Tests use synthetic filters and generated FFmpeg color frames only. No owner
media, real model inference, long GPU renders, or mobile playback are tested.
"""
from __future__ import annotations

import errno
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from app.video.cinematic_filtergraph_transport_qa27 import private_filtergraph_script_command


def test_private_script_permissions_command_identity_and_cleanup(tmp_path: Path) -> None:
    graph = '[0:v]null[v]'
    original = ['ffmpeg', '-filter_complex', graph, '-map', '[v]', 'output.mp4']
    with private_filtergraph_script_command(original, directory=tmp_path) as changed:
        assert original[2] == graph
        assert changed[1] == '-filter_complex_script'
        assert graph not in changed
        script = Path(changed[2])
        assert script.read_text(encoding='utf-8') == graph
        if os.name == 'posix':
            assert script.stat().st_mode & 0o777 == 0o600
    assert not script.exists()
    assert not list(tmp_path.iterdir())


def test_private_script_removed_on_cancellation_or_error(tmp_path: Path) -> None:
    script = None
    with pytest.raises(TimeoutError):
        with private_filtergraph_script_command(
            ['ffmpeg', '-filter_complex', '[0:v]null[v]'], directory=tmp_path,
        ) as changed:
            script = Path(changed[2])
            raise TimeoutError('synthetic cancellation')
    assert script is not None and not script.exists()


@pytest.mark.parametrize('command', [
    [], ['ffmpeg'], ['ffmpeg', '-filter_complex'],
    ['ffmpeg', '-filter_complex', ''],
    ['ffmpeg', '-filter_complex', 'a', '-filter_complex', 'b'],
    ['ffmpeg', '-filter_complex', 'a', '-filter_complex_script', 'b'],
])
def test_malformed_commands_fail_without_temp_artifacts(tmp_path: Path, command: list[str]) -> None:
    with pytest.raises(ValueError):
        with private_filtergraph_script_command(command, directory=tmp_path):
            pytest.fail('Invalid command unexpectedly accepted')
    assert not list(tmp_path.iterdir())


def test_symlink_directory_is_rejected(tmp_path: Path) -> None:
    real = tmp_path / 'real'
    real.mkdir()
    link = tmp_path / 'link'
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip('Platform does not permit symlink creation')
    with pytest.raises(ValueError):
        with private_filtergraph_script_command(
            ['ffmpeg', '-filter_complex', '[0:v]null[v]'], directory=link,
        ):
            pytest.fail('Symlink directory unexpectedly accepted')
    assert not list(real.iterdir())


def _media_tools() -> tuple[str, str]:
    ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        if os.environ.get('CINEMATIC_REQUIRE_REAL_MEDIA') == '1':
            pytest.fail('Strict real-media QA requires FFmpeg and FFprobe')
        pytest.skip('Optional synthetic FFmpeg test requires local media tools')
    return ffmpeg, ffprobe


def test_genuine_synthetic_ffmpeg_two_shot_concat_and_full_decode(tmp_path: Path) -> None:
    ffmpeg, ffprobe = _media_tools()
    graph = ('[0:v]fps=24,format=yuv420p[v0];'
             '[1:v]fps=24,format=yuv420p[v1];'
             '[v0][v1]concat=n=2:v=1:a=0[v]')
    output = tmp_path / 'synthetic-master.mp4'
    command = [ffmpeg, '-nostdin', '-y', '-hide_banner', '-loglevel', 'error',
               '-f', 'lavfi', '-i', 'color=c=red:s=64x64:r=24:d=1',
               '-f', 'lavfi', '-i', 'color=c=blue:s=64x64:r=24:d=1',
               '-filter_complex', graph, '-map', '[v]', '-an',
               '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-r', '24',
               '-movflags', '+faststart', str(output)]
    with private_filtergraph_script_command(command, directory=tmp_path) as safe:
        result = subprocess.run(safe, capture_output=True, timeout=40, check=False)
    assert result.returncode == 0, f'Synthetic FFmpeg exited {result.returncode}'
    probe = subprocess.run(
        [ffprobe, '-v', 'error', '-select_streams', 'v:0',
         '-show_entries', 'stream=nb_frames,codec_name,avg_frame_rate',
         '-of', 'default=noprint_wrappers=1', str(output)],
        capture_output=True, text=True, timeout=15, check=True,
    )
    assert 'nb_frames=48' in probe.stdout
    assert 'codec_name=h264' in probe.stdout
    assert 'avg_frame_rate=24/1' in probe.stdout
    decode = subprocess.run(
        [ffmpeg, '-v', 'error', '-i', str(output), '-f', 'null', '-'],
        capture_output=True, timeout=20, check=False,
    )
    assert decode.returncode == 0
    assert not list(tmp_path.glob('.cinematic-filter-*'))


def test_real_linux_large_graph_inline_e2big_but_script_executes(tmp_path: Path) -> None:
    ffmpeg, _ = _media_tools()
    if sys.platform != 'linux' or os.sysconf('SC_PAGE_SIZE') != 4096:
        pytest.skip('Linux 4KiB-page execve boundary only')
    # A real, parseable 700-filter graph; padding is whitespace, not private text.
    graph = '[0:v]' + ','.join('null' + ' ' * 190 for _ in range(700)) + '[v]'
    assert len(graph.encode('utf-8')) > 131072
    command = [ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error',
               '-f', 'lavfi', '-i', 'color=c=red:s=16x16:r=1:d=1',
               '-filter_complex', graph, '-map', '[v]', '-frames:v', '1',
               '-f', 'null', '-']
    with pytest.raises(OSError) as failure:
        subprocess.run(command, capture_output=True, timeout=30, check=False)
    assert failure.value.errno == errno.E2BIG
    with private_filtergraph_script_command(command, directory=tmp_path) as safe:
        assert graph not in safe
        result = subprocess.run(safe, capture_output=True, timeout=40, check=False)
    assert result.returncode == 0, f'FFmpeg script launch failed ({result.returncode})'
    assert not list(tmp_path.iterdir())
