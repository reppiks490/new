"""QA23: genuine synthetic FFmpeg proof of source metadata leaking into a private master.

A source MP4's format tags must never be inherited by an assembled master.
This test uses only synthetic video and canaries; it does not inspect owner media.
"""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


# Synthetic sentinel values only; never print real project tags or owner media.
_SOURCE_TITLE = 'SYNTHETIC_SOURCE_PRIVATE_TITLE_QA23'
_SOURCE_COMMENT = 'SYNTHETIC_SOURCE_PRIVATE_COMMENT_QA23'
_FORBIDDEN_TAG_KEYS = frozenset({
    'title', 'comment', 'description', 'synopsis', 'artist', 'author',
    'copyright', 'creation_time', 'location', 'location-eng', 'gps',
})


def _tools() -> tuple[str, str]:
    ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    if ffmpeg and ffprobe:
        encoders = subprocess.run(
            [ffmpeg, '-hide_banner', '-encoders'],
            capture_output=True, text=True, timeout=20, check=False,
        )
        if encoders.returncode == 0 and 'libx264' in encoders.stdout:
            return ffmpeg, ffprobe
    if os.environ.get('CINEMATIC_REQUIRE_REAL_MEDIA') == '1':
        pytest.fail('QA23 requires local FFmpeg, FFprobe and libx264')
    pytest.skip('synthetic FFmpeg tools unavailable')


def _run(args: list[str]) -> bytes:
    result = subprocess.run(args, capture_output=True, timeout=180, check=False)
    assert result.returncode == 0, 'synthetic media command failed'
    return result.stdout


def _tags(ffprobe: str, path: Path) -> dict:
    data = json.loads(_run([
        ffprobe, '-v', 'error', '-show_entries', 'format_tags',
        '-of', 'json', str(path),
    ]))
    return data['format'].get('tags', {})


def test_real_assembly_does_not_inherit_private_source_mp4_tags(monkeypatch, tmp_path):
    ffmpeg, ffprobe = _tools()
    monkeypatch.setenv('CHARACTER3D_STUDIO_WORKSPACE', str(tmp_path))
    models = importlib.import_module('app.video.cinematic_models')
    service = importlib.import_module('app.video.cinematic_service')
    storage = importlib.import_module('app.video.storage')
    requests = importlib.import_module('app.video.cinematic_requests')

    project = service.create_project(models.ProjectCreateRequest(
        title='Synthetic metadata isolation',
        master_prompt='Synthetic frames only; no owner content',
        target_duration_seconds=10, delivery_fps=24,
        delivery_resolution='480p', aspect_ratio='16:9',
    ))
    scene_id = '9' * 32
    shots = [models.CinematicShot(
        shot_id=f'{index + 60:032x}', ordinal=index + 1,
        title=f'Synthetic {index + 1}', prompt='Synthetic colors',
        duration_seconds=5,
    ) for index in range(2)]
    scene = models.CinematicScene(
        scene_id=scene_id, ordinal=1, title='Synthetic',
        target_duration_seconds=10, shots=shots,
    )
    project = service.update_project(
        project.id, models.ProjectUpdateRequest(expected_revision=1, scenes=[scene]),
    )
    linked = []
    for index, color in enumerate(('red', 'blue')):
        asset_id = f'{index + 160:032x}'
        path = storage.video_asset_path(asset_id, 'mp4')
        command = [
            ffmpeg, '-nostdin', '-y', '-hide_banner', '-loglevel', 'error',
            '-f', 'lavfi', '-i', f'color=c={color}:s=160x90:r=24:d=5',
            '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
        ]
        if index == 0:
            command.extend([
                '-metadata', f'title={_SOURCE_TITLE}',
                '-metadata', f'comment={_SOURCE_COMMENT}',
            ])
        _run(command + ['-movflags', '+faststart', str(path)])
        if index == 0:
            # Reproduction control: the source really contains the sentinels.
            source_tags = _tags(ffprobe, path)
            assert source_tags.get('title') == _SOURCE_TITLE
            assert source_tags.get('comment') == _SOURCE_COMMENT
        record = storage.put_video_record('video_job', {
            'status': 'succeeded', 'stage': 'Ready', 'progress': 100,
            'project_id': project.id, 'scene_id': scene_id,
            'shot_id': shots[index].shot_id,
            'project_revision': project.revision, 'asset_id': asset_id,
            'asset_url': f'/api/video/assets/{asset_id}.mp4',
        })
        linked.append(shots[index].model_copy(update={
            'latest_job_id': record['id'],
            'latest_rendered_project_revision': project.revision,
        }))
    project = service.update_project(
        project.id, models.ProjectUpdateRequest(
            expected_revision=project.revision,
            scenes=[scene.model_copy(update={'shots': linked})],
        ),
    )
    assert service.project_render_status(project.id)['ready_for_assembly']
    master = service.assemble_project_master(
        project.id, requests.AssembleMasterRequest(
            expected_revision=project.revision, ffmpeg_path='ffmpeg',
        ),
    )
    assert master['status'] == 'ready'
    output = storage.video_asset_path(master['asset_id'], 'mp4')
    tags = _tags(ffprobe, output)
    # Do not dump metadata values to CI logs: report offending keys only.
    inherited = sorted(set(tags) & _FORBIDDEN_TAG_KEYS)
    assert inherited == [], f'master inherited disallowed metadata keys: {inherited}'
